"""
Инфраструктурный слой модуля доставки.
Только этот файл знает, где и как хранятся доставки, заказы и курьеры.
Бизнес-правил здесь нет.
"""
from abc import ABC, abstractmethod

from sqlalchemy.orm import Session

from app import config, memory_db
from app.models import Delivery, Order, User


class DeliveryRepository(ABC):
    """Абстрактный интерфейс репозитория доставок."""

    @abstractmethod
    def get_order_by_id(self, order_id: int):
        """Найти заказ по id. Если нет - вернуть None."""

    @abstractmethod
    def get_user_by_id(self, user_id: int):
        """Найти пользователя (курьера) по id. Если нет - вернуть None."""

    @abstractmethod
    def get_delivery_by_id(self, delivery_id: int):
        """Найти доставку по id. Если нет - вернуть None."""

    @abstractmethod
    def get_courier_delivery_by_status(self, courier_id: int, status: str):
        """Найти доставку курьера с указанным статусом. Если нет - вернуть None."""

    @abstractmethod
    def save_delivery(self, order_id: int, courier_id: int, status: str) -> int:
        """Сохранить новую доставку и вернуть её id."""

    @abstractmethod
    def update_delivery_and_order(self, delivery, order) -> None:
        """
        Сохранить изменения доставки и заказа вместе (одной транзакцией).
        order может быть None.
        """


class PostgresDeliveryRepository(DeliveryRepository):
    """Реализация для PostgreSQL через SQLAlchemy ORM."""

    def __init__(self, db: Session):
        self.db = db

    def get_order_by_id(self, order_id: int):
        return self.db.query(Order).filter(Order.id == order_id).first()

    def get_user_by_id(self, user_id: int):
        return self.db.query(User).filter(User.id == user_id).first()

    def get_delivery_by_id(self, delivery_id: int):
        return self.db.query(Delivery).filter(Delivery.id == delivery_id).first()

    def get_courier_delivery_by_status(self, courier_id: int, status: str):
        return self.db.query(Delivery).filter(
            Delivery.courier_id == courier_id,
            Delivery.status == status,
        ).first()

    def save_delivery(self, order_id: int, courier_id: int, status: str) -> int:
        new_delivery = Delivery(
            order_id=order_id,
            courier_id=courier_id,
            status=status,
        )
        self.db.add(new_delivery)
        self.db.commit()
        self.db.refresh(new_delivery)
        return new_delivery.id

    def update_delivery_and_order(self, delivery, order) -> None:
        if order:
            self.db.add(order)
        self.db.add(delivery)
        # Один commit на оба изменения, как было в MVP.
        self.db.commit()


class InMemoryDeliveryRepository(DeliveryRepository):
    """Реализация, которая хранит данные в памяти (app/memory_db.py)."""

    def get_order_by_id(self, order_id: int):
        return memory_db.orders.get(order_id)

    def get_user_by_id(self, user_id: int):
        return memory_db.users.get(user_id)

    def get_delivery_by_id(self, delivery_id: int):
        return memory_db.deliveries.get(delivery_id)

    def get_courier_delivery_by_status(self, courier_id: int, status: str):
        for delivery in memory_db.deliveries.values():
            if delivery.courier_id == courier_id and delivery.status == status:
                return delivery
        return None

    def save_delivery(self, order_id: int, courier_id: int, status: str) -> int:
        delivery_id = len(memory_db.deliveries) + 1
        memory_db.deliveries[delivery_id] = memory_db.DeliveryRecord(
            id=delivery_id,
            order_id=order_id,
            courier_id=courier_id,
            status=status,
        )
        return delivery_id

    def update_delivery_and_order(self, delivery, order) -> None:
        if order:
            memory_db.orders[order.id] = order
        memory_db.deliveries[delivery.id] = delivery


def get_delivery_repository(db: Session) -> DeliveryRepository:
    """
    Выбор реализации репозитория по настройке REPOSITORY.
    Хранилище меняется здесь, а service.py и router.py остаются как есть.
    """
    if config.REPOSITORY == "memory":
        return InMemoryDeliveryRepository()
    return PostgresDeliveryRepository(db)
