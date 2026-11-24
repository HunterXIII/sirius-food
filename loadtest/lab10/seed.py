"""Создаёт синтетического студента и блюдо в базе нагрузочного стенда."""
from uuid import uuid4

from sqlalchemy import select

from app.core.jwt import create_access_token
from app.database import SessionLocal
from app.models import MenuItem, Role, User
from app.modules.menu.repository import PostgresMenuRepository


def main():
    with SessionLocal.begin() as db:
        role_id = db.scalar(select(Role.id).where(Role.name == "student"))
        user = User(email=f"locust-{uuid4().hex}@example.com", password_hash="unused", role_id=role_id)
        item = MenuItem(name="Сырники для Locust", price=150.25, is_available=True)
        db.add_all([user, item])
        db.flush()
        item_id = item.id
        token = create_access_token(user.id)

    with SessionLocal() as db:
        PostgresMenuRepository(db).invalidate_cache()
    print(f"LOCUST_MENU_ITEM_ID={item_id}")
    print(f"LOCUST_ORDER_TOKEN={token}")


if __name__ == "__main__":
    main()
