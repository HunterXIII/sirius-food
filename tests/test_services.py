"""
Unit-тесты слоя бизнес-логики (service.py).
PostgreSQL не нужен: в сервисы передаются in-memory репозитории.
Запуск: python -m unittest discover tests -v
"""
import unittest
from decimal import Decimal
from unittest.mock import patch

from app import memory_db
from app.core.security import verify_password
from app.exceptions import NotFoundError, ForbiddenError, AccessDeniedError
from app.modules.orders.amounts import order_total
from app.modules.orders.repository import InMemoryOrderRepository
from app.modules.orders.service import OrderService
from app.modules.users.repository import InMemoryUserRepository
from app.modules.users.service import UserService
from app.modules.menu.repository import InMemoryMenuRepository
from app.modules.menu.service import MenuService
from app.modules.delivery.repository import InMemoryDeliveryRepository
from app.modules.delivery.service import DeliveryService


def add_user(user_id, email, balance=0.0, is_blocked=False, role="student"):
    """Положить пользователя прямо в memory_db (пароль сервисам здесь не нужен)."""
    role_id = next(r.id for r in memory_db.roles.values() if r.name == role)
    memory_db.users[user_id] = memory_db.UserRecord(
        id=user_id,
        email=email,
        phone=None,
        balance=balance,
        is_blocked=is_blocked,
        password_hash="",
        role_id=role_id,
    )


class OrderServiceTest(unittest.TestCase):
    def setUp(self):
        memory_db.clear()
        add_user(1, "ivan@sirius.ru", balance=500.0)
        memory_db.menu_items[1] = memory_db.MenuItemRecord(
            id=1, name="Борщ", price=200.0, is_available=True
        )
        memory_db.menu_items[2] = memory_db.MenuItemRecord(
            id=2, name="Компот", price=50.0, is_available=False
        )
        self.service = OrderService(InMemoryOrderRepository())
        # Задачи Celery не ставим в настоящую очередь Redis: подменяем их заглушками.
        for task in ("generate_order_pdf", "send_order_email", "send_order_sms"):
            patcher = patch(f"app.modules.orders.service.{task}")
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_create_order_waits_for_payment(self):
        order_id = self.service.create_order(user_id=1, item_id=1, quantity=2)

        self.assertEqual(order_id, 1)
        self.assertEqual(memory_db.users[1].balance, 500.0)
        self.assertEqual(memory_db.orders[1].status, "processing")

    def test_order_total_multiplies_and_rounds_half_up(self):
        self.assertEqual(order_total(1.005, 3), Decimal("3.02"))

    def test_order_total_accepts_smallest_cent_and_highest_total(self):
        self.assertEqual(order_total(0.005, 1), Decimal("0.01"))
        self.assertEqual(order_total(9999999999.99, 1), Decimal("9999999999.99"))

    def test_order_total_rejects_invalid_values_before_and_after_rounding(self):
        for unit_price in (float("nan"), float("inf"), -1, 0, 0.004, 9999999999.995, 10000000000):
            with self.subTest(unit_price=unit_price):
                with self.assertRaisesRegex(ValueError, "^Недопустимая сумма заказа$"):
                    order_total(unit_price, 1)

    def test_pay_order_writes_off_balance_once(self):
        order_id = self.service.create_order(user_id=1, item_id=1, quantity=2)

        self.service.pay_order(order_id, current_user=memory_db.users[1])
        self.service.pay_order(order_id, current_user=memory_db.users[1])

        self.assertEqual(memory_db.users[1].balance, 100.0)
        self.assertEqual(memory_db.orders[order_id].status, "paid")

    def test_not_enough_money(self):
        order_id = self.service.create_order(user_id=1, item_id=1, quantity=3)

        with self.assertRaises(ValueError):
            self.service.pay_order(order_id, current_user=memory_db.users[1])

        # Неудачная оплата не меняет баланс и статус заказа.
        self.assertEqual(memory_db.users[1].balance, 500.0)
        self.assertEqual(memory_db.orders[order_id].status, "processing")

    def test_unavailable_item(self):
        with self.assertRaises(ValueError):
            self.service.create_order(user_id=1, item_id=2, quantity=1)

    def test_user_not_found(self):
        with self.assertRaises(NotFoundError):
            self.service.create_order(user_id=99, item_id=1, quantity=1)

    def test_cancel_own_order(self):
        order_id = self.service.create_order(user_id=1, item_id=1, quantity=1)

        self.service.cancel_order(order_id, current_user=memory_db.users[1])

        self.assertEqual(memory_db.orders[order_id].status, "cancelled")

    def test_cancel_foreign_order(self):
        # IDOR: студент 2 подставляет id заказа студента 1.
        add_user(2, "petr@sirius.ru")
        order_id = self.service.create_order(user_id=1, item_id=1, quantity=1)

        with self.assertRaises(AccessDeniedError):
            self.service.cancel_order(order_id, current_user=memory_db.users[2])

        self.assertEqual(memory_db.orders[order_id].status, "processing")

    def test_cancel_twice(self):
        order_id = self.service.create_order(user_id=1, item_id=1, quantity=1)
        self.service.cancel_order(order_id, current_user=memory_db.users[1])

        with self.assertRaises(ValueError):
            self.service.cancel_order(order_id, current_user=memory_db.users[1])


class UserServiceTest(unittest.TestCase):
    def setUp(self):
        memory_db.clear()
        self.service = UserService(InMemoryUserRepository())

    def test_register_with_zero_balance(self):
        user = self.service.register(email="ivan@sirius.ru", password="password123", phone=None)

        self.assertEqual(user.balance, 0.0)
        self.assertFalse(user.is_blocked)
        self.assertEqual(user.role.name, "student")

    def test_register_stores_only_password_hash(self):
        user = self.service.register(email="ivan@sirius.ru", password="password123", phone=None)

        # В хранилище не сам пароль, а bcrypt-хеш, и пароль с ним сходится.
        self.assertNotEqual(user.password_hash, "password123")
        self.assertTrue(user.password_hash.startswith("$2b$"))
        self.assertTrue(verify_password("password123", user.password_hash))

    def test_register_duplicate_email(self):
        self.service.register(email="ivan@sirius.ru", password="password123", phone=None)

        with self.assertRaises(ValueError):
            self.service.register(email="ivan@sirius.ru", password="password123", phone=None)

    def test_top_up(self):
        user = self.service.register(email="ivan@sirius.ru", password="password123", phone=None)

        self.assertEqual(self.service.top_up(user_id=user.id, amount=1000, current_user=user), 1000)

    def test_top_up_foreign_balance(self):
        user = self.service.register(email="ivan@sirius.ru", password="password123", phone=None)
        add_user(2, "petr@sirius.ru")

        with self.assertRaises(AccessDeniedError):
            self.service.top_up(user_id=user.id, amount=100, current_user=memory_db.users[2])

        self.assertEqual(user.balance, 0.0)

    def test_top_up_over_limit(self):
        user = self.service.register(email="ivan@sirius.ru", password="password123", phone=None)

        with self.assertRaises(ValueError):
            self.service.top_up(user_id=user.id, amount=50001, current_user=user)

    def test_top_up_blocked_user(self):
        user = self.service.register(email="ivan@sirius.ru", password="password123", phone=None)
        user.is_blocked = True

        with self.assertRaises(ForbiddenError):
            self.service.top_up(user_id=user.id, amount=100, current_user=user)

    def test_change_role(self):
        add_user(1, "ivan@sirius.ru")

        self.service.change_role(user_id=1, role="cook")

        self.assertEqual(memory_db.users[1].role.name, "cook")

    def test_change_to_unknown_role(self):
        add_user(1, "ivan@sirius.ru")

        with self.assertRaises(ValueError):
            self.service.change_role(user_id=1, role="director")


class MenuServiceTest(unittest.TestCase):
    def setUp(self):
        memory_db.clear()
        self.service = MenuService(InMemoryMenuRepository())

    def test_create_duplicate_name(self):
        self.service.create_item(name="Борщ", price=250)

        with self.assertRaises(ValueError):
            self.service.create_item(name="Борщ", price=300)

    def test_update_only_given_fields(self):
        item_id = self.service.create_item(name="Борщ", price=250)

        self.service.update_item(item_id, price=270)

        item = memory_db.menu_items[item_id]
        self.assertEqual(item.name, "Борщ")
        self.assertEqual(item.price, 270)
        self.assertTrue(item.is_available)

    def test_update_not_found(self):
        with self.assertRaises(NotFoundError):
            self.service.update_item(99, name="Суп")


class DeliveryServiceTest(unittest.TestCase):
    def setUp(self):
        memory_db.clear()
        # Студент 1 - владелец заказов, студент 4 - посторонний.
        # Курьер 2 обычный, курьер 3 заблокирован, курьер 5 - другой курьер.
        add_user(1, "client@sirius.ru")
        add_user(2, "courier@sirius.ru", role="courier")
        add_user(3, "blocked@sirius.ru", is_blocked=True, role="courier")
        add_user(4, "other@sirius.ru")
        add_user(5, "courier2@sirius.ru", role="courier")
        # Заказы 1 и 2 оплачены, заказ 3 ещё нет.
        memory_db.orders[1] = memory_db.OrderRecord(
            id=1, user_id=1, item_id=1, quantity=1, status="paid"
        )
        memory_db.orders[2] = memory_db.OrderRecord(
            id=2, user_id=1, item_id=1, quantity=1, status="paid"
        )
        memory_db.orders[3] = memory_db.OrderRecord(
            id=3, user_id=1, item_id=1, quantity=1, status="processing"
        )
        self.service = DeliveryService(InMemoryDeliveryRepository())

    def test_assign_courier(self):
        delivery_id = self.service.assign_courier(order_id=1, courier_id=2)

        self.assertEqual(memory_db.deliveries[delivery_id].status, "in_progress")

    def test_assign_to_unpaid_order(self):
        with self.assertRaises(ValueError):
            self.service.assign_courier(order_id=3, courier_id=2)

    def test_assign_not_courier(self):
        with self.assertRaises(ValueError):
            self.service.assign_courier(order_id=1, courier_id=4)

    def test_assign_blocked_courier(self):
        with self.assertRaises(ForbiddenError):
            self.service.assign_courier(order_id=1, courier_id=3)

    def test_courier_already_busy(self):
        self.service.assign_courier(order_id=1, courier_id=2)

        with self.assertRaises(ValueError):
            self.service.assign_courier(order_id=2, courier_id=2)

    def test_complete_delivery_marks_order_delivered(self):
        delivery_id = self.service.assign_courier(order_id=1, courier_id=2)

        self.service.complete_delivery(delivery_id, current_user=memory_db.users[2])

        self.assertEqual(memory_db.deliveries[delivery_id].status, "completed")
        self.assertEqual(memory_db.orders[1].status, "delivered")

    def test_complete_twice(self):
        delivery_id = self.service.assign_courier(order_id=1, courier_id=2)
        self.service.complete_delivery(delivery_id, current_user=memory_db.users[2])

        with self.assertRaises(ValueError):
            self.service.complete_delivery(delivery_id, current_user=memory_db.users[2])

    def test_complete_not_found(self):
        with self.assertRaises(NotFoundError):
            self.service.complete_delivery(99, current_user=memory_db.users[2])

    def test_complete_by_other_courier(self):
        delivery_id = self.service.assign_courier(order_id=1, courier_id=2)

        with self.assertRaises(AccessDeniedError):
            self.service.complete_delivery(delivery_id, current_user=memory_db.users[5])

        self.assertEqual(memory_db.deliveries[delivery_id].status, "in_progress")

    def test_get_delivery_by_courier_and_customer(self):
        delivery_id = self.service.assign_courier(order_id=1, courier_id=2)

        # Курьер этой доставки и студент, чей заказ, видят доставку.
        self.service.get_delivery(delivery_id, current_user=memory_db.users[2])
        self.service.get_delivery(delivery_id, current_user=memory_db.users[1])

    def test_get_foreign_delivery(self):
        delivery_id = self.service.assign_courier(order_id=1, courier_id=2)

        # Другой курьер и посторонний студент - нет.
        with self.assertRaises(AccessDeniedError):
            self.service.get_delivery(delivery_id, current_user=memory_db.users[5])
        with self.assertRaises(AccessDeniedError):
            self.service.get_delivery(delivery_id, current_user=memory_db.users[4])
