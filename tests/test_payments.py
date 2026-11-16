from datetime import timedelta
import json
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.database import Base
from app.models import Delivery, MenuItem, Order, OutboxEvent, Payment, Refund, Role, User, utcnow
from app.modules.delivery.repository import PostgresDeliveryRepository
from app.modules.delivery.service import DeliveryService
from app.modules.payments import router as api
from app.modules.payments.service import PaymentService
from app.modules.payments.yookassa import YooKassa
from app.workers.consumer import DeliveryFailed, OrderPaid, save_event


class GatewayStub:
    def __init__(self):
        self.payments = {}
        self.refunds = {}
        self.requests = []
        self.timeout_after_create = False
        self.timeout_after_refund = False
        self.fail_posts = False

    def __call__(self, request):
        path = request.url.path
        key = request.headers.get("Idempotence-Key")
        self.requests.append((request.method, path, key))
        if request.method == "POST":
            if self.fail_posts:
                return httpx.Response(500)
            body = json.loads(request.content)
            if path == "/v3/payments":
                remote_id = f"test-{key}"
                if remote_id not in self.payments:
                    self.payments[remote_id] = {
                        "id": remote_id, "status": "pending", "amount": body["amount"],
                        "paid": False, "metadata": body["metadata"],
                        "confirmation": {"confirmation_url": "https://example.test/checkout"},
                    }
                    if self.timeout_after_create:
                        raise httpx.ReadTimeout("response lost", request=request)
                return httpx.Response(200, json=self.payments[remote_id])

            remote_id = f"test-{key}"
            if remote_id not in self.refunds:
                self.refunds[remote_id] = {
                    "id": remote_id, "payment_id": body["payment_id"],
                    "amount": body["amount"], "status": "pending",
                }
                if self.timeout_after_refund:
                    raise httpx.ReadTimeout("response lost", request=request)
            return httpx.Response(200, json=self.refunds[remote_id])

        objects = self.refunds if "/refunds/" in path else self.payments
        result = objects.get(path.rsplit("/", 1)[-1])
        return httpx.Response(200, json=result) if result else httpx.Response(404)

    def client(self):
        return httpx.Client(base_url="https://api.yookassa.ru/v3/", transport=httpx.MockTransport(self))


class PaymentsTest(TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        engine = create_engine(f"sqlite:///{directory}/payments.db")
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        self.sessions = sessionmaker(engine, autoflush=False)
        with self.sessions.begin() as db:
            db.add(Role(id=1, name="student"))
            db.add_all([
                User(id=1, email="student@example.test", role_id=1, password_hash="-", balance=300),
                User(id=2, email="other@example.test", role_id=1, password_hash="-", balance=0),
                MenuItem(id=1, name="Борщ", price=999, is_available=True),
                Order(id=1, item_id=1, quantity=2, user_id=1, status="processing", total_amount="200.50"),
                Order(id=2, item_id=1, quantity=1, user_id=1, status="processing", total_amount="100"),
                Order(id=3, item_id=1, quantity=1, user_id=2, status="processing", total_amount="100"),
            ])

        self.stub = GatewayStub()
        self.user_id = 1
        self.enterContext(patch.object(settings, "REPOSITORY", "postgres"))
        self.enterContext(patch.object(api, "configured", return_value=True))
        self.enterContext(patch.object(api, "SessionLocal", self.sessions))
        self.enterContext(patch.object(api, "gateway_client", self.stub.client))
        self.enterContext(patch.object(api, "configured_gateway", side_effect=lambda client: YooKassa(client, "test", "test")))
        self.enterContext(patch("app.workers.consumer.SessionLocal", self.sessions))

        app = FastAPI()
        app.include_router(api.router, prefix="/payments")
        app.dependency_overrides[get_current_user] = self.current_user
        self.http = self.enterContext(TestClient(app))

    def current_user(self):
        with self.sessions() as db:
            user = db.get(User, self.user_id)
            _ = user.role
            return user

    def pay(self, order_id=1, key="first", **body):
        return self.http.post("/payments", json={"order_id": order_id, **body}, headers={"Idempotency-Key": key})

    def notice(self, event, remote_id):
        # Уведомление само по себе ничего не подтверждает.
        return self.http.post("/payments/webhook", json={
            "type": "notification", "event": event, "object": {"id": remote_id, "paid": True},
        })

    def run_worker(self, model):
        with self.stub.client() as client:
            PaymentService(self.sessions, YooKassa(client, "test", "test")).process_next(model)

    def force_retry(self, model, job_id):
        with self.sessions.begin() as db:
            db.get(model, job_id).next_check_at = utcnow() - timedelta(seconds=1)

    def test_idempotency_and_ownership(self):
        self.assertEqual(self.pay(amount="0.01").status_code, 409)
        self.assertEqual(self.pay(order_id=3).status_code, 404)
        first = self.pay(amount="200.50")
        self.assertEqual(first.status_code, 200)
        data = first.json()
        self.assertEqual(data["amount"], "200.50")
        self.assertEqual(data["confirmation_url"], "https://example.test/checkout")
        self.assertEqual(self.pay(amount="200.50").json(), data)
        self.assertEqual(self.pay().status_code, 409)
        self.assertEqual(self.pay(order_id=2).status_code, 409)
        self.assertEqual(self.pay(key="another").status_code, 409)
        self.user_id = 2
        self.assertEqual(self.http.get(f"/payments/{data['id']}").status_code, 404)
        self.assertEqual(len(self.stub.payments), 1)

    def test_declined_and_new_attempt(self):
        first = self.pay().json()
        gateway_id = f"test-{first['id']}"
        self.stub.payments[gateway_id].update(status="canceled", cancellation_details={"reason": "insufficient_funds"})
        self.assertEqual(self.notice("payment.canceled", gateway_id).status_code, 200)
        declined = self.http.get(f"/payments/{first['id']}").json()
        self.assertEqual((declined["status"], declined["reason"], declined["order_status"]),
                         ("canceled", "insufficient_funds", "processing"))
        second = self.pay(key="second").json()
        self.assertNotEqual(second["id"], first["id"])
        self.assertEqual(len(self.stub.payments), 2)

    def test_payment_confirmation_and_full_refund_after_no_courier(self):
        payment_id = self.pay().json()["id"]
        remote_id = f"test-{payment_id}"
        self.assertEqual(self.notice("payment.succeeded", remote_id).status_code, 200)
        self.assertEqual(self.http.get(f"/payments/{payment_id}").json()["order_status"], "processing")
        self.stub.payments[remote_id].update(status="succeeded", paid=True)
        self.stub.payments[remote_id]["amount"]["value"] = "201.00"
        self.assertEqual(self.notice("payment.succeeded", remote_id).status_code, 409)
        self.stub.payments[remote_id]["amount"]["value"] = "200.50"
        for _ in range(2):
            self.assertEqual(self.notice("payment.succeeded", remote_id).status_code, 200)
        with self.sessions() as db:
            event = db.scalars(select(OutboxEvent).filter_by(routing_key="order.paid")).one()
            paid = OrderPaid.model_validate(event.payload)
        save_event(paid, "delivery", "order.paid")
        with self.sessions() as db:
            event = db.scalars(select(OutboxEvent).filter_by(routing_key="delivery.failed")).one()
            failed = DeliveryFailed.model_validate(event.payload)
        save_event(failed, "orders", "delivery.failed")
        save_event(failed, "orders", "delivery.failed")
        self.stub.timeout_after_refund = True
        self.run_worker(Refund)
        with self.sessions() as db:
            refund = db.scalars(select(Refund)).one()
            self.assertEqual(refund.reason, "timeout")
            self.assertEqual(db.get(User, 1).balance, 300)
        self.force_retry(Refund, refund.id)
        self.run_worker(Refund)
        remote_refund_id = f"test-{refund.id}"
        self.assertEqual(
            [key for method, path, key in self.stub.requests if method == "POST" and path == "/v3/refunds"],
            [refund.id, refund.id],
        )
        self.stub.refunds[remote_refund_id]["status"] = "succeeded"
        for _ in range(2):
            self.assertEqual(self.notice("refund.succeeded", remote_refund_id).status_code, 200)
        data = self.http.get(f"/payments/{payment_id}").json()
        self.assertEqual(data["order_status"], "cancelled")
        self.assertEqual(data["cancellation_reason"], "Свободный курьер не найден")
        self.assertEqual(data["status"], "succeeded")
        self.assertEqual((data["refund"]["status"], data["refund"]["amount"]), ("succeeded", "200.50"))
        self.assertEqual(len(self.stub.refunds), 1)

    def test_lost_response_is_retried_with_same_key(self):
        self.stub.timeout_after_create = True
        initial = self.pay()
        self.assertEqual(initial.status_code, 202)
        self.assertEqual(initial.json()["reason"], "timeout")
        payment_id = initial.json()["id"]
        self.force_retry(Payment, payment_id)
        self.run_worker(Payment)
        keys = [key for method, _, key in self.stub.requests if method == "POST"]
        self.assertEqual(keys, [payment_id, payment_id])
        self.assertEqual(len(self.stub.payments), 1)
        self.assertEqual(self.http.get(f"/payments/{payment_id}").json()["status"], "pending")

    def test_expired_idempotency_window_stops_outbound_writes(self):
        self.stub.fail_posts = True
        payment_id = self.pay().json()["id"]
        with self.sessions.begin() as db:
            job = db.get(Payment, payment_id)
            job.first_sent_at = utcnow() - timedelta(hours=24)
            job.next_check_at = utcnow() - timedelta(seconds=1)
        self.run_worker(Payment)
        self.assertEqual(self.http.get(f"/payments/{payment_id}").json()["status"], "needs_review")
        self.assertEqual(len(self.stub.requests), 1)

    def test_webhook_recovers_missing_gateway_id(self):
        self.stub.timeout_after_create = True
        response = self.pay().json()
        gateway_id = f"test-{response['id']}"
        self.stub.payments[gateway_id].update(status="succeeded", paid=True)
        self.assertEqual(self.notice("payment.succeeded", gateway_id).status_code, 200)
        with self.sessions() as db:
            self.assertEqual(db.get(Payment, response["id"]).gateway_id, gateway_id)
            self.assertEqual(db.scalar(select(func.count()).select_from(OutboxEvent)), 1)

    def test_delivery_completed_after_worker_reconciles_payment(self):
        with self.sessions.begin() as db:
            db.add(Role(id=2, name="courier"))
            db.add(User(id=3, email="courier@example.test", role_id=2, password_hash="-", balance=0))

        payment_id = self.pay().json()["id"]
        self.stub.payments[f"test-{payment_id}"].update(status="succeeded", paid=True)
        self.force_retry(Payment, payment_id)
        self.run_worker(Payment)
        with self.sessions() as db:
            event = db.scalars(select(OutboxEvent).filter_by(routing_key="order.paid")).one()
            paid = OrderPaid.model_validate(event.payload)
        save_event(paid, "delivery", "order.paid")
        with self.sessions() as db:
            delivery = db.scalars(select(Delivery)).one()
            courier = db.get(User, 3)
            DeliveryService(PostgresDeliveryRepository(db)).complete_delivery(delivery.id, courier)

        data = self.http.get(f"/payments/{payment_id}").json()
        self.assertEqual(data["order_status"], "delivered")
        self.assertEqual(data["delivery_status"], "completed")
        self.assertIsNone(data["refund"])

    def test_four_retries_then_reconciliation_required(self):
        self.stub.fail_posts = True
        now = utcnow() + timedelta(seconds=1)
        self.enterContext(patch("app.modules.payments.service.uniform", return_value=1.1))
        with patch("app.modules.payments.service.utcnow", return_value=now) as clock:
            payment_id = self.pay().json()["id"]
            for interval in (1, 2, 4, 8):
                with self.sessions() as db:
                    payment = db.get(Payment, payment_id)
                    delay = (payment.next_check_at.replace(tzinfo=now.tzinfo) - now).total_seconds()
                    self.assertAlmostEqual(delay, interval * 1.1)
                now += timedelta(seconds=interval * 1.1 + 0.1)
                clock.return_value = now
                self.run_worker(Payment)
        data = self.http.get(f"/payments/{payment_id}").json()
        self.assertEqual(data["status"], "needs_review")
        self.assertEqual(self.pay(key="other").status_code, 409)
        self.assertEqual(len(self.stub.requests), 5)
        self.assertTrue(all(key == payment_id for _, _, key in self.stub.requests))
