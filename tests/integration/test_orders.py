from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.jwt import create_access_token
from app.models import MenuItem, Order, Role, User


@pytest.fixture
def order_input(db_sessions):
    with db_sessions.begin() as db:
        assert db.scalar(select(func.count()).select_from(Order)) == 0
        role_id = db.scalar(select(Role.id).where(Role.name == "student"))
        user = User(email="student@example.com", password_hash="unused", role_id=role_id)
        item = MenuItem(name="Сырники", price=150.25, is_available=True)
        db.add_all([user, item])
        db.flush()
        return user.id, item.id


def test_create_order_saves_committed_row(client, db_sessions, order_input):
    user_id, item_id = order_input
    response = client.post(
        "/orders/create",
        headers={"Authorization": f"Bearer {create_access_token(user_id)}"},
        json={"item_id": item_id, "quantity": 2},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "success"

    # Читаем из другой сессии, чтобы проверить фактический commit.
    with db_sessions() as db:
        order = db.get(Order, response.json()["order_id"])
        assert order is not None
        assert (order.user_id, order.item_id, order.quantity) == (user_id, item_id, 2)
        assert order.status == "processing"
        assert order.total_amount == Decimal("300.50")
        assert order.correlation_id == response.headers["X-Correlation-ID"]


@pytest.mark.parametrize(("authenticated", "quantity", "status"), [(False, 1, 401), (True, 0, 400)])
def test_rejected_order_does_not_write(client, db_sessions, order_input, authenticated, quantity, status):
    user_id, item_id = order_input
    headers = {"Authorization": f"Bearer {create_access_token(user_id)}"} if authenticated else {}
    response = client.post("/orders/create", headers=headers, json={"item_id": item_id, "quantity": quantity})

    assert response.status_code == status, response.text
    with db_sessions() as db:
        assert db.scalar(select(func.count()).select_from(Order)) == 0
