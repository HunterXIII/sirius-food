"""
Инфраструктурный слой модуля меню.
Только этот файл знает, где и как хранятся блюда.
Бизнес-правил здесь нет.
"""
import json
from abc import ABC, abstractmethod

from sqlalchemy.orm import Session

from app import memory_db
from app.core.config import settings
from app.core.redis import redis_client
from app.models import MenuItem

# Ключ кеша со всем меню и время его жизни (5 минут).
MENU_ALL_KEY = "menu:all"
MENU_ALL_TTL = 300


def item_to_dict(item) -> dict:
    """Блюдо (ORM-объект или запись memory_db) -> словарь для ответа API."""
    return {
        "id": item.id,
        "name": item.name,
        "price": item.price,
        "is_available": item.is_available,
    }


class MenuRepository(ABC):
    """Абстрактный интерфейс репозитория меню."""

    @abstractmethod
    def get_item_by_id(self, item_id: int):
        """Найти блюдо по id. Если нет - вернуть None."""

    @abstractmethod
    def get_item_by_name(self, name: str):
        """Найти блюдо по названию. Если нет - вернуть None."""

    @abstractmethod
    def save_item(self, name: str, price: float, is_available: bool) -> int:
        """Сохранить новое блюдо и вернуть его id."""

    @abstractmethod
    def update_item(self, item) -> None:
        """Сохранить изменения блюда."""

    @abstractmethod
    def get_all_items(self) -> list[dict]:
        """Всё меню списком словарей (отсортировано по id)."""


class PostgresMenuRepository(MenuRepository):
    """
    Реализация для PostgreSQL через SQLAlchemy ORM.
    Чтение меню кешируется в Redis (Cache-Aside).
    """

    def __init__(self, db: Session):
        self.db = db

    def get_item_by_id(self, item_id: int):
        return self.db.query(MenuItem).filter(MenuItem.id == item_id).first()

    def get_item_by_name(self, name: str):
        return self.db.query(MenuItem).filter(MenuItem.name == name).first()

    def save_item(self, name: str, price: float, is_available: bool) -> int:
        new_item = MenuItem(
            name=name,
            price=price,
            is_available=is_available,
        )
        self.db.add(new_item)
        self.db.commit()
        self.db.refresh(new_item)
        return new_item.id

    def update_item(self, item) -> None:
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)

    def get_all_items(self) -> list[dict]:
        """
        Возвращает всё меню.
        Сначала проверяет кеш Redis (Cache-Aside).
        При промахе (miss) идёт в БД и кеширует результат.
        """
        # 1. Проверка кеша
        cached_data = redis_client.get(MENU_ALL_KEY)
        if cached_data is not None:
            # Hit: возвращаем данные из кеша
            return json.loads(cached_data)

        # 2. Miss: идём в БД
        items = self.db.query(MenuItem).order_by(MenuItem.id).all()
        items_data = [item_to_dict(item) for item in items]

        # 3. Сохраняем в кеш с TTL 5 минут
        redis_client.setex(MENU_ALL_KEY, MENU_ALL_TTL, json.dumps(items_data, ensure_ascii=False))
        return items_data


class InMemoryMenuRepository(MenuRepository):
    """Реализация, которая хранит данные в памяти (app/memory_db.py)."""

    def get_item_by_id(self, item_id: int):
        return memory_db.menu_items.get(item_id)

    def get_item_by_name(self, name: str):
        for item in memory_db.menu_items.values():
            if item.name == name:
                return item
        return None

    def save_item(self, name: str, price: float, is_available: bool) -> int:
        item_id = len(memory_db.menu_items) + 1
        memory_db.menu_items[item_id] = memory_db.MenuItemRecord(
            id=item_id,
            name=name,
            price=price,
            is_available=is_available,
        )
        return item_id

    def update_item(self, item) -> None:
        memory_db.menu_items[item.id] = item

    def get_all_items(self) -> list[dict]:
        items = sorted(memory_db.menu_items.values(), key=lambda item: item.id)
        return [item_to_dict(item) for item in items]


def get_menu_repository(db: Session) -> MenuRepository:
    """
    Выбор реализации репозитория по настройке REPOSITORY.
    Хранилище меняется здесь, а service.py и router.py остаются как есть.
    """
    if settings.REPOSITORY == "memory":
        return InMemoryMenuRepository()
    return PostgresMenuRepository(db)
