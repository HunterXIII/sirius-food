"""
Слой бизнес-логики модуля доставки.
Здесь нет импортов fastapi и sqlalchemy.
"""
from app.exceptions import NotFoundError, ForbiddenError
from app.modules.delivery.repository import DeliveryRepository


class DeliveryService:
    """Бизнес-правила назначения курьера и завершения доставки."""

    def __init__(self, repository: DeliveryRepository):
        # Инверсия зависимостей: репозиторий передают через конструктор.
        self.repository = repository

    def assign_courier(self, order_id: int, courier_id: int) -> int:
        """
        Назначение курьера на заказ. Возвращает id доставки.
        NotFoundError - нет заказа или курьера, ForbiddenError - курьер
        заблокирован, ValueError - нарушено бизнес-правило.
        """
        order = self.repository.get_order_by_id(order_id)
        if not order:
            raise NotFoundError("Заказ не найден")

        # Назначить курьера можно только на оплаченный заказ.
        if order.status != "paid":
            raise ValueError("Курьера можно назначить только на оплаченный заказ")

        courier = self.repository.get_user_by_id(courier_id)
        if not courier:
            raise NotFoundError("Курьер не найден")

        if courier.is_blocked:
            raise ForbiddenError("Курьер заблокирован и не может быть назначен")

        # Один курьер - одна активная доставка.
        if self.repository.get_courier_delivery_by_status(courier_id, "in_progress"):
            raise ValueError("У курьера уже есть активная доставка")

        return self.repository.save_delivery(order_id, courier_id, status="in_progress")

    def complete_delivery(self, delivery_id: int) -> None:
        """
        Завершение доставки: доставка - "completed", заказ - "delivered".
        NotFoundError - нет доставки, ValueError - доставка уже завершена или отменена.
        """
        delivery = self.repository.get_delivery_by_id(delivery_id)
        if not delivery:
            raise NotFoundError("Доставка не найдена")

        if delivery.status == "completed":
            raise ValueError("Доставка уже завершена")

        if delivery.status == "cancelled":
            raise ValueError("Отменённую доставку нельзя завершить")

        delivery.status = "completed"

        # Вместе с доставкой заказ становится доставленным.
        order = self.repository.get_order_by_id(delivery.order_id)
        if order:
            order.status = "delivered"

        self.repository.update_delivery_and_order(delivery, order)
