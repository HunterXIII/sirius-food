"""
Слой бизнес-логики модуля доставки.
Здесь нет импортов fastapi и sqlalchemy.
"""
from app.exceptions import NotFoundError, ForbiddenError, AccessDeniedError
from app.modules.delivery.repository import DeliveryRepository


class DeliveryService:
    """Бизнес-правила назначения курьера, просмотра и завершения доставки."""

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

        # Назначить можно только пользователя с ролью courier.
        if courier.role.name != "courier":
            raise ValueError("Пользователь не является курьером")

        if courier.is_blocked:
            raise ForbiddenError("Курьер заблокирован и не может быть назначен")

        # Один курьер - одна активная доставка.
        if self.repository.get_courier_delivery_by_status(courier_id, "in_progress"):
            raise ValueError("У курьера уже есть активная доставка")

        return self.repository.save_delivery(order_id, courier_id, status="in_progress")

    def get_delivery(self, delivery_id: int, current_user):
        """
        Просмотр доставки. Видят её только двое: курьер этой доставки
        и студент, чей это заказ.
        NotFoundError - нет доставки, AccessDeniedError - доставка чужая.
        """
        delivery = self.repository.get_delivery_by_id(delivery_id)
        if not delivery:
            raise NotFoundError("Доставка не найдена")

        order = self.repository.get_order_by_id(delivery.order_id)
        is_courier = delivery.courier_id == current_user.id
        is_customer = order is not None and order.user_id == current_user.id
        if not is_courier and not is_customer:
            raise AccessDeniedError("Нет доступа к этой доставке")

        return delivery

    def complete_delivery(self, delivery_id: int, current_user) -> None:
        """
        Завершение доставки: доставка - "completed", заказ - "delivered".
        NotFoundError - нет доставки, AccessDeniedError - доставка другого курьера,
        ValueError - доставка уже завершена или отменена.
        """
        delivery = self.repository.get_delivery_by_id(delivery_id)
        if not delivery:
            raise NotFoundError("Доставка не найдена")

        # Защита от IDOR: завершить доставку может только её курьер.
        if delivery.courier_id != current_user.id:
            raise AccessDeniedError("Это доставка другого курьера")

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
