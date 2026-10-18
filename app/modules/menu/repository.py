"""
Инфраструктурный слой модуля меню.
Только этот файл знает, где и как хранятся блюда.
Бизнес-правил здесь нет.
"""
import json
import time
from abc import ABC, abstractmethod

import redis
from sqlalchemy.orm import Session

from app import memory_db
from app.core.config import settings
from app.core.redis import redis_client
from app.models import Category, MenuItem

# Ключ кеша со всем меню и время его жизни (5 минут).
MENU_ALL_KEY = "menu:all"
MENU_ALL_TTL = 300
# Категория кешируется под ключом menu:category:{id} на 10 минут.
MENU_CATEGORY_TTL = 600


def item_to_dict(item) -> dict:
    """Блюдо (ORM-объект или запись memory_db) -> словарь для ответа API."""
    return {
        "id": item.id,
        "name": item.name,
        "price": item.price,
        "is_available": item.is_available,
        "category_id": item.category_id,
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
    def save_item(self, name: str, price: float, is_available: bool, category_id: int | None) -> int:
        """Сохранить новое блюдо и вернуть его id."""

    @abstractmethod
    def update_item(self, item) -> None:
        """Сохранить изменения блюда."""

    @abstractmethod
    def get_all_items(self) -> list[dict]:
        """Всё меню списком словарей (отсортировано по id)."""

    @abstractmethod
    def get_category(self, category_id: int) -> dict | None:
        """Категория с её блюдами. Если категории нет - None."""

    @abstractmethod
    def invalidate_cache(self) -> None:
        """Сбросить кеш меню (вызывается после изменения меню)."""

    @abstractmethod
    def warm_up_cache(self) -> None:
        """Прогрев кеша при старте приложения."""


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

    def save_item(self, name: str, price: float, is_available: bool, category_id: int | None) -> int:
        new_item = MenuItem(
            name=name,
            price=price,
            is_available=is_available,
            category_id=category_id,
        )
        self.db.add(new_item)
        self.db.commit()
        self.db.refresh(new_item)
        return new_item.id

    def update_item(self, item) -> None:
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)

    def _cache_aside(self, key: str, ttl: int, load_from_db):
        """
        Cache-Aside с защитой от cache stampede.
        Hit - данные из Redis. Miss - в БД идёт только запрос, который взял
        блокировку lock:<key>, остальные ждут, пока он заполнит кеш.
        load_from_db - функция, которая читает данные из БД.
        """
        try:
            while True:
                # 1. Проверка кеша
                cached_data = redis_client.get(key)
                if cached_data is not None:
                    # Hit: возвращаем данные из кеша
                    return json.loads(cached_data)

                # 2. Miss: пробуем взять блокировку, не дожидаясь её.
                # timeout=10 - если запрос упадёт, блокировка сама снимется через 10 секунд.
                lock = redis_client.lock(f"lock:{key}", timeout=10)
                if lock.acquire(blocking=False):
                    try:
                        # Пока мы брали блокировку, кеш мог заполнить другой запрос.
                        cached_data = redis_client.get(key)
                        if cached_data is not None:
                            return json.loads(cached_data)
                        # Идём в БД и сохраняем результат в кеш с TTL.
                        data = load_from_db()
                        # None (например, категории нет) не кешируем.
                        if data is not None:
                            redis_client.setex(key, ttl, json.dumps(data, ensure_ascii=False))
                        return data
                    finally:
                        lock.release()

                # Блокировку держит другой запрос: ждём и снова смотрим в кеш.
                time.sleep(0.05)
        except redis.ConnectionError:
            # Redis недоступен. Кеш - только ускоритель, поэтому читаем
            # прямо из БД: приложение работает, но медленнее.
            return load_from_db()

    def get_all_items(self) -> list[dict]:
        """Возвращает всё меню (из кеша, при промахе из БД)."""
        def load_from_db():
            items = self.db.query(MenuItem).order_by(MenuItem.id).all()
            return [item_to_dict(item) for item in items]

        return self._cache_aside(MENU_ALL_KEY, MENU_ALL_TTL, load_from_db)

    def get_category(self, category_id: int) -> dict | None:
        """Категория с блюдами (из кеша, при промахе из БД)."""
        def load_from_db():
            category = self.db.query(Category).filter(Category.id == category_id).first()
            if not category:
                return None
            items = (
                self.db.query(MenuItem)
                .filter(MenuItem.category_id == category_id)
                .order_by(MenuItem.id)
                .all()
            )
            return {
                "id": category.id,
                "name": category.name,
                "items": [item_to_dict(item) for item in items],
            }

        return self._cache_aside(f"menu:category:{category_id}", MENU_CATEGORY_TTL, load_from_db)

    def invalidate_cache(self) -> None:
        """Сбрасывает кеш меню: всё меню и все категории."""
        try:
            redis_client.delete(MENU_ALL_KEY)
            # Блюдо могло перейти из одной категории в другую,
            # поэтому проще сбросить кеш всех категорий.
            for key in redis_client.scan_iter("menu:category:*"):
                redis_client.delete(key)
        except redis.ConnectionError:
            # Redis недоступен - сбрасывать нечего, изменение в БД уже сохранено.
            pass

    def warm_up_cache(self) -> None:
        """Заполняет menu:all из БД, чтобы первый запрос не шёл в базу."""
        # В Redis мог остаться кеш от прошлого запуска, а меню с тех пор
        # могли поменять прямо в БД. Поэтому сначала сбрасываем.
        self.invalidate_cache()
        self.get_all_items()


class InMemoryMenuRepository(MenuRepository):
    """Реализация, которая хранит данные в памяти (app/memory_db.py)."""

    def get_item_by_id(self, item_id: int):
        return memory_db.menu_items.get(item_id)

    def get_item_by_name(self, name: str):
        for item in memory_db.menu_items.values():
            if item.name == name:
                return item
        return None

    def save_item(self, name: str, price: float, is_available: bool, category_id: int | None) -> int:
        item_id = len(memory_db.menu_items) + 1
        memory_db.menu_items[item_id] = memory_db.MenuItemRecord(
            id=item_id,
            name=name,
            price=price,
            is_available=is_available,
            category_id=category_id,
        )
        return item_id

    def update_item(self, item) -> None:
        memory_db.menu_items[item.id] = item

    def get_all_items(self) -> list[dict]:
        items = sorted(memory_db.menu_items.values(), key=lambda item: item.id)
        return [item_to_dict(item) for item in items]

    def get_category(self, category_id: int) -> dict | None:
        category = memory_db.categories.get(category_id)
        if not category:
            return None
        items = [item for item in self.get_all_items() if item["category_id"] == category_id]
        return {"id": category.id, "name": category.name, "items": items}

    def invalidate_cache(self) -> None:
        # Кеша у in-memory реализации нет, сбрасывать нечего.
        pass

    def warm_up_cache(self) -> None:
        # Кеша нет - прогревать нечего.
        pass


def get_menu_repository(db: Session) -> MenuRepository:
    """
    Выбор реализации репозитория по настройке REPOSITORY.
    Хранилище меняется здесь, а service.py и router.py остаются как есть.
    """
    if settings.REPOSITORY == "memory":
        return InMemoryMenuRepository()
    return PostgresMenuRepository(db)
