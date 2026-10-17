"""
Хранилище данных в оперативной памяти.
Им пользуются in-memory репозитории вместо PostgreSQL:
в unit-тестах и при запуске с REPOSITORY=memory.
Данные живут, пока работает процесс.
"""
from dataclasses import dataclass


@dataclass
class UserRecord:
    id: int
    email: str
    phone: str | None
    balance: float
    is_blocked: bool


@dataclass
class MenuItemRecord:
    id: int
    name: str
    price: float
    is_available: bool


@dataclass
class OrderRecord:
    id: int
    user_id: int
    item_id: int
    quantity: int
    status: str


@dataclass
class DeliveryRecord:
    id: int
    order_id: int
    courier_id: int
    status: str


# "Таблицы": id -> запись.
# Общие для всех модулей, чтобы заказ видел пользователей и блюда.
users: dict[int, UserRecord] = {}
menu_items: dict[int, MenuItemRecord] = {}
orders: dict[int, OrderRecord] = {}
deliveries: dict[int, DeliveryRecord] = {}


def clear():
    """Удалить все данные (нужно перед каждым тестом)."""
    users.clear()
    menu_items.clear()
    orders.clear()
    deliveries.clear()
