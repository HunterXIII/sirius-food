"""
Хранилище данных в оперативной памяти.
Им пользуются in-memory репозитории вместо PostgreSQL:
в unit-тестах и при запуске с REPOSITORY=memory.
Данные живут, пока работает процесс.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass
class RoleRecord:
    id: int
    name: str


@dataclass
class UserRecord:
    id: int
    email: str
    phone: str | None
    balance: float
    is_blocked: bool
    password_hash: str
    role_id: int

    @property
    def role(self) -> RoleRecord:
        """Роль по role_id, как relationship("Role") в models.py."""
        return roles[self.role_id]


@dataclass
class CategoryRecord:
    id: int
    name: str


@dataclass
class MenuItemRecord:
    id: int
    name: str
    price: float
    is_available: bool
    category_id: int | None = None


@dataclass
class OrderRecord:
    id: int
    user_id: int
    item_id: int
    quantity: int
    status: str
    created_at: datetime | None = None
    total_amount: Decimal | None = None


@dataclass
class DeliveryRecord:
    id: int
    order_id: int
    courier_id: int
    status: str


@dataclass
class RefreshTokenRecord:
    id: int
    user_id: int
    token_hash: str
    expires_at: datetime
    is_revoked: bool


# Категории меню, как в миграции lab4.
CATEGORY_NAMES = ["Супы", "Горячее", "Гарниры", "Салаты", "Напитки", "Выпечка"]

# "Таблицы": id -> запись.
# Общие для всех модулей, чтобы заказ видел пользователей и блюда.
roles: dict[int, RoleRecord] = {}
users: dict[int, UserRecord] = {}
categories: dict[int, CategoryRecord] = {}
menu_items: dict[int, MenuItemRecord] = {}
orders: dict[int, OrderRecord] = {}
deliveries: dict[int, DeliveryRecord] = {}
refresh_tokens: dict[int, RefreshTokenRecord] = {}


def clear():
    """Удалить все данные (нужно перед каждым тестом)."""
    users.clear()
    menu_items.clear()
    orders.clear()
    deliveries.clear()
    refresh_tokens.clear()

    # Роли - справочник. В PostgreSQL их заполняет миграция, здесь - мы сами.
    roles.clear()
    for role_id, name in enumerate(["student", "cook", "courier", "admin"], start=1):
        roles[role_id] = RoleRecord(id=role_id, name=name)

    # Категории меню - тоже справочник из миграции.
    categories.clear()
    for category_id, name in enumerate(CATEGORY_NAMES, start=1):
        categories[category_id] = CategoryRecord(id=category_id, name=name)


# Заполнить роли при старте.
clear()
