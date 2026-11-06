"""Проверка шагов Saga и отката транзакций на SQLite. Брокер не требуется."""
import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.events import order_paid
from app.database import Base
from app.models import Delivery, KitchenOrder, MenuItem, Order, OutboxEvent, ProcessedEvent, Role, User
from app.workers.consumer import DeliveryFailed, OrderCancelled, OrderPaid, save_event


class SagaTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False)
        patcher = patch("app.workers.consumer.SessionLocal", self.sessions)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.payment = order_paid(1, 1, 200)
        self.paid = OrderPaid.model_validate(self.payment)
        with self.sessions.begin() as db:
            db.add_all([Role(id=1, name="student"), Role(id=2, name="courier")])
            db.add(User(id=1, email="student@sirius.ru", balance=300, password_hash="unused", role_id=1))
            db.add(MenuItem(id=1, name="Суп", price=100, is_available=True))
            db.add(Order(id=1, user_id=1, item_id=1, quantity=2, status="paid"))
            db.add(OutboxEvent(
                id=self.payment["event_id"], routing_key="order.paid", payload=self.payment, published=True,
            ))

    def fail_delivery(self):
        save_event(self.paid, "delivery", "order.paid")
        with self.sessions() as db:
            event = db.query(OutboxEvent).filter_by(routing_key="delivery.failed").one()
            return DeliveryFailed.model_validate(event.payload)

    def test_assign_free_courier_once(self):
        with self.sessions.begin() as db:
            db.add(User(id=2, email="courier@sirius.ru", balance=0, password_hash="unused", role_id=2))

        save_event(self.paid, "delivery", "order.paid")
        self.assertIsNone(save_event(self.paid, "delivery", "order.paid"))

        with self.sessions() as db:
            delivery = db.query(Delivery).one()
            self.assertEqual(delivery.courier_id, 2)
            self.assertEqual(delivery.status, "in_progress")
            self.assertEqual(db.get(Order, 1).status, "paid")
            self.assertEqual(db.query(OutboxEvent).count(), 1)

    def test_refund_original_amount_once(self):
        failed = self.fail_delivery()
        self.assertIsNone(save_event(self.paid, "delivery", "order.paid"))
        # Цена уже изменилась, возвращать нужно ранее списанные 200.
        with self.sessions.begin() as db:
            db.get(MenuItem, 1).price = 999

        save_event(failed, "orders", "delivery.failed")
        self.assertIsNone(save_event(failed, "orders", "delivery.failed"))
        another_failure = failed.model_copy(update={"event_id": uuid4()})
        save_event(another_failure, "orders", "delivery.failed")

        with self.sessions() as db:
            self.assertEqual(db.get(User, 1).balance, 500)
            self.assertEqual(db.get(Order, 1).status, "cancelled")
            self.assertEqual(db.query(Delivery).one().status, "failed")
            self.assertEqual(db.query(OutboxEvent).filter_by(routing_key="delivery.failed").count(), 1)
            self.assertEqual(db.query(OutboxEvent).filter_by(routing_key="order.cancelled").count(), 1)

    def test_failed_compensation_rolls_back_all_changes(self):
        failed = self.fail_delivery()
        with patch("app.workers.consumer.order_cancelled", side_effect=RuntimeError("Сбой записи")):
            with self.assertRaises(RuntimeError):
                save_event(failed, "orders", "delivery.failed")

        with self.sessions() as db:
            self.assertEqual(db.get(User, 1).balance, 300)
            self.assertEqual(db.get(Order, 1).status, "paid")
            self.assertEqual(db.query(ProcessedEvent).filter_by(consumer="orders").count(), 0)
            self.assertEqual(db.query(OutboxEvent).filter_by(routing_key="order.cancelled").count(), 0)

        save_event(failed, "orders", "delivery.failed")
        with self.sessions() as db:
            self.assertEqual(db.get(User, 1).balance, 500)

    def test_late_payment_does_not_restart_cancelled_order(self):
        failed = self.fail_delivery()
        save_event(failed, "orders", "delivery.failed")
        with self.sessions() as db:
            event = db.query(OutboxEvent).filter_by(routing_key="order.cancelled").one()
            cancelled = OrderCancelled.model_validate(event.payload)

        # Отмена дошла до кухни раньше исходного события оплаты.
        save_event(cancelled, "kitchen", "order.cancelled")
        save_event(self.paid, "kitchen", "order.paid")
        late_payment = self.paid.model_copy(update={"event_id": uuid4()})
        save_event(late_payment, "delivery", "order.paid")

        with self.sessions() as db:
            self.assertEqual(db.query(KitchenOrder).one().status, "cancelled")
            self.assertEqual(db.query(Delivery).one().status, "failed")
            self.assertEqual(db.get(User, 1).balance, 500)
            self.assertEqual(db.query(OutboxEvent).count(), 3)
