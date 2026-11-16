"""100 concurrent payment requests against PostgreSQL and a fake YooKassa API."""

import asyncio
import json
import os
from statistics import median, quantiles
from threading import Lock
from time import perf_counter
from unittest.mock import patch
from uuid import uuid4

import httpx
from fastapi import FastAPI
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.database import Base
from app.models import Category, Delivery, MenuItem, Order, Payment, Refund, Role, User
from app.modules.payments import router as api
from app.modules.payments.yookassa import YooKassa

REQUESTS = 100


class MockYooKassa:
    def __init__(self):
        self.posts = 0
        self.lock = Lock()

    def __call__(self, request):
        assert request.method == "POST" and request.url.path == "/v3/payments"
        with self.lock:
            self.posts += 1
        body = json.loads(request.content)
        return httpx.Response(200, json={
            "id": request.headers["Idempotence-Key"], "status": "pending", "paid": False,
            "amount": body["amount"], "metadata": body["metadata"],
            "confirmation": {"confirmation_url": "https://example.test/checkout"},
        })

    def client(self):
        return httpx.Client(base_url="https://api.yookassa.ru/v3/", transport=httpx.MockTransport(self))


async def run_batch(client, order_ids, label):
    async def pay(order_id):
        start = perf_counter()
        result = await client.post("/payments", json={"order_id": order_id},
                                   headers={"Idempotency-Key": f"load-{order_id}"})
        result.raise_for_status()
        return result.json(), (perf_counter() - start) * 1000

    started = perf_counter()
    rows = await asyncio.gather(*(pay(order_id) for order_id in order_ids))
    elapsed = perf_counter() - started
    results, latencies = zip(*rows)
    p95 = quantiles(latencies, n=20)[18]
    print(f"{label}: {len(results)} requests in {elapsed:.2f}s, "
          f"p50={median(latencies):.0f}ms, p95={p95:.0f}ms")
    return {row["id"] for row in results}


async def exercise(sessions):
    gateway = MockYooKassa()
    student = User(id=1, role=Role(name="student"))
    app = FastAPI()
    app.include_router(api.router, prefix="/payments")
    app.dependency_overrides[get_current_user] = lambda: student

    with (
        patch.object(settings, "REPOSITORY", "postgres"),
        patch.object(api, "SessionLocal", sessions),
        patch.object(api, "configured", return_value=True),
        patch.object(api, "gateway_client", gateway.client),
        patch.object(api, "configured_gateway", side_effect=lambda client: YooKassa(client, "test", "test")),
    ):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local.test") as client:
            unique = await run_batch(client, range(1, REQUESTS + 1), "Distinct orders")
            assert len(unique) == gateway.posts == REQUESTS
            repeated = await run_batch(client, [REQUESTS + 1] * REQUESTS, "Same order and key")
            assert len(repeated) == 1 and gateway.posts == REQUESTS + 1
            data = (await client.get(f"/payments/{next(iter(repeated))}")).json()
            assert data["status"] == "pending" and data["confirmation_url"]
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Payment)) == REQUESTS + 1
    print(f"{REQUESTS + 1} local payments, {gateway.posts} gateway POSTs, no duplicates")


def main():
    # Тест работает в собственной схеме, окружение приложения не подменяется.
    url = os.environ["PAYMENTS_TEST_DATABASE_URL"]
    schema = f"payments_test_{uuid4().hex}"
    admin = create_engine(url, hide_parameters=True)
    with admin.begin() as conn:
        conn.exec_driver_sql(f"CREATE SCHEMA {schema}")
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"}, hide_parameters=True)
    try:
        models = (Role, User, Category, MenuItem, Order, Payment, Refund, Delivery)
        Base.metadata.create_all(engine, tables=[model.__table__ for model in models])
        sessions = sessionmaker(engine)
        with sessions.begin() as db:
            db.add(Role(id=1, name="student"))
            db.add(User(id=1, email="load@example.test", role_id=1, password_hash="unused"))
            db.add(MenuItem(id=1, name="Тестовое блюдо", price=100, is_available=True))
            db.flush()
            db.add_all([
                Order(id=n, user_id=1, item_id=1, quantity=1, status="processing", total_amount=100)
                for n in range(1, REQUESTS + 2)
            ])
        asyncio.run(exercise(sessions))
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.exec_driver_sql(f"DROP SCHEMA {schema} CASCADE")
        admin.dispose()


if __name__ == "__main__":
    main()
