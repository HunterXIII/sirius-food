"""
Слой бизнес-логики модуля заказов.
Здесь нет импортов fastapi и sqlalchemy: сервис не знает ни про HTTP, ни про БД.
"""
from app.exceptions import NotFoundError, AccessDeniedError
from app.modules.orders.repository import OrderRepository


class OrderService:
    """Бизнес-правила оформления, просмотра и отмены заказов."""

    def __init__(self, repository: OrderRepository):
        # Инверсия зависимостей: репозиторий передают снаружи через конструктор,
        # сервису всё равно, PostgreSQL это или память.
        self.repository = repository

    def create_order(self, user_id: int, item_id: int, quantity: int) -> int:
        """
        Сценарий оформления заказа. Возвращает id созданного заказа.
        NotFoundError - нет пользователя или блюда,
        ValueError - нарушено бизнес-правило.
        """
        user = self.repository.get_user_by_id(user_id)
        if not user:
            raise NotFoundError("Пользователь не найден")

        item = self.repository.get_menu_item_by_id(item_id)
        if not item:
            raise NotFoundError("Блюдо не найдено")

        if not item.is_available:
            raise ValueError("Блюдо недоступно")

        total_cost = item.price * quantity
        if user.balance < total_cost:
            raise ValueError("Недостаточно средств на балансе студента")

        # Списываем деньги и сохраняем заказ. Как именно - решает репозиторий.
        self.repository.update_user_balance(user, user.balance - total_cost)
        return self.repository.save_order(user_id, item_id, quantity, status="processing")

    def get_kitchen_orders(self) -> list:
        """Заказы, которые кухне нужно приготовить (статус processing)."""
        return self.repository.get_orders_by_status("processing")

    def cancel_order(self, order_id: int, current_user):
        """
        Отменяет заказ. Проверяет, что заказ принадлежит текущему пользователю.
        NotFoundError - заказа нет, AccessDeniedError - заказ чужой,
        ValueError - заказ уже нельзя отменить.
        """
        order = self.repository.get_order_by_id(order_id)
        if order is None:
            raise NotFoundError("Заказ не найден")

        # Защита от IDOR: order_id пришёл от клиента, ему нельзя верить.
        # Отменить можно только свой заказ.
        if order.user_id != current_user.id:
            raise AccessDeniedError("Нельзя отменить чужой заказ")

        if order.status != "processing":
            raise ValueError("Отменить можно только заказ, который ещё готовится")

        order.status = "cancelled"
        self.repository.update_order(order)
        return order
