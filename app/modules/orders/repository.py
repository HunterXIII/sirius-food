"""
Инфраструктурный слой модуля заказов.
Только этот файл знает, где и как хранятся данные (SQLAlchemy, таблицы, память).
Бизнес-правил здесь нет.
"""
from abc import ABC, abstractmethod
from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import memory_db
from app.core.config import settings
from app.models import Order, User, MenuItem


class OrderRepository(ABC):
    """
    Абстрактный интерфейс репозитория заказов.
    Сервис зависит только от него и не знает, какая реализация ему передана.
    """

    @abstractmethod
    def get_user_by_id(self, user_id: int):
        """Найти пользователя по id. Если нет - вернуть None."""

    @abstractmethod
    def get_menu_item_by_id(self, item_id: int):
        """Найти блюдо по id. Если нет - вернуть None."""

    @abstractmethod
    def save_order(self, user_id: int, item_id: int, quantity: int, status: str) -> int:
        """Сохранить новый заказ и вернуть его id."""

    @abstractmethod
    def update_user_balance(self, user, new_balance: float) -> None:
        """Сохранить новый баланс пользователя."""

    @abstractmethod
    def get_order_by_id(self, order_id: int):
        """Найти заказ по id. Если нет - вернуть None."""

    @abstractmethod
    def get_orders_by_status(self, status: str) -> list:
        """Все заказы с указанным статусом."""

    @abstractmethod
    def update_order(self, order) -> None:
        """Сохранить изменения заказа."""

    @abstractmethod
    def count_orders_by_day(self, day: date) -> int:
        """Сколько заказов создано в этот день."""


class PostgresOrderRepository(OrderRepository):
    """Реализация для PostgreSQL через SQLAlchemy ORM."""

    def __init__(self, db: Session):
        self.db = db

    def get_user_by_id(self, user_id: int):
        return self.db.query(User).filter(User.id == user_id).first()

    def get_menu_item_by_id(self, item_id: int):
        return self.db.query(MenuItem).filter(MenuItem.id == item_id).first()

    def save_order(self, user_id: int, item_id: int, quantity: int, status: str) -> int:
        new_order = Order(
            user_id=user_id,
            item_id=item_id,
            quantity=quantity,
            status=status,
        )
        self.db.add(new_order)
        self.db.commit()
        self.db.refresh(new_order)
        return new_order.id

    def update_user_balance(self, user, new_balance: float) -> None:
        user.balance = new_balance
        self.db.add(user)
        self.db.commit()

    def get_order_by_id(self, order_id: int):
        return self.db.query(Order).filter(Order.id == order_id).first()

    def get_orders_by_status(self, status: str) -> list:
        return self.db.query(Order).filter(Order.status == status).order_by(Order.id).all()

    def update_order(self, order) -> None:
        self.db.add(order)
        self.db.commit()

    def count_orders_by_day(self, day: date) -> int:
        # SELECT count(*) FROM orders WHERE date(created_at) = :day
        return self.db.query(Order).filter(func.date(Order.created_at) == day).count()


class InMemoryOrderRepository(OrderRepository):
    """Реализация, которая хранит данные в памяти (app/memory_db.py)."""

    def get_user_by_id(self, user_id: int):
        return memory_db.users.get(user_id)

    def get_menu_item_by_id(self, item_id: int):
        return memory_db.menu_items.get(item_id)

    def save_order(self, user_id: int, item_id: int, quantity: int, status: str) -> int:
        order_id = len(memory_db.orders) + 1
        memory_db.orders[order_id] = memory_db.OrderRecord(
            id=order_id,
            user_id=user_id,
            item_id=item_id,
            quantity=quantity,
            status=status,
            created_at=datetime.now(),
        )
        return order_id

    def update_user_balance(self, user, new_balance: float) -> None:
        memory_db.users[user.id].balance = new_balance

    def get_order_by_id(self, order_id: int):
        return memory_db.orders.get(order_id)

    def get_orders_by_status(self, status: str) -> list:
        return [order for order in memory_db.orders.values() if order.status == status]

    def update_order(self, order) -> None:
        memory_db.orders[order.id] = order

    def count_orders_by_day(self, day: date) -> int:
        return len([
            order for order in memory_db.orders.values()
            if order.created_at and order.created_at.date() == day
        ])


def get_order_repository(db: Session) -> OrderRepository:
    """
    Выбор реализации репозитория по настройке REPOSITORY.
    Хранилище меняется здесь, а service.py и router.py остаются как есть.
    """
    if settings.REPOSITORY == "memory":
        return InMemoryOrderRepository()
    return PostgresOrderRepository(db)
