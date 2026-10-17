"""
Unit-тесты слоя бизнес-логики (service.py).
PostgreSQL не нужен: в сервисы передаются in-memory репозитории.
Запуск: python -m unittest discover tests -v
"""
import unittest

from app import memory_db
from app.core.security import verify_password
from app.exceptions import NotFoundError, ForbiddenError
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

    def test_create_order_writes_off_balance(self):
        order_id = self.service.create_order(user_id=1, item_id=1, quantity=2)

        self.assertEqual(order_id, 1)
        self.assertEqual(memory_db.users[1].balance, 100.0)
        self.assertEqual(memory_db.orders[1].status, "processing")

    def test_not_enough_money(self):
        with self.assertRaises(ValueError):
            self.service.create_order(user_id=1, item_id=1, quantity=3)

        # Ни баланс, ни заказы не должны измениться.
        self.assertEqual(memory_db.users[1].balance, 500.0)
        self.assertEqual(memory_db.orders, {})

    def test_unavailable_item(self):
        with self.assertRaises(ValueError):
            self.service.create_order(user_id=1, item_id=2, quantity=1)

    def test_user_not_found(self):
        with self.assertRaises(NotFoundError):
            self.service.create_order(user_id=99, item_id=1, quantity=1)


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

        self.assertEqual(self.service.top_up(user_id=user.id, amount=1000), 1000)

    def test_top_up_over_limit(self):
        user = self.service.register(email="ivan@sirius.ru", password="password123", phone=None)

        with self.assertRaises(ValueError):
            self.service.top_up(user_id=user.id, amount=50001)

    def test_top_up_blocked_user(self):
        user = self.service.register(email="ivan@sirius.ru", password="password123", phone=None)
        user.is_blocked = True

        with self.assertRaises(ForbiddenError):
            self.service.top_up(user_id=user.id, amount=100)


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
        # Курьер 2 обычный, курьер 3 заблокирован.
        add_user(2, "courier@sirius.ru", role="courier")
        add_user(3, "blocked@sirius.ru", is_blocked=True, role="courier")
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

    def test_assign_blocked_courier(self):
        with self.assertRaises(ForbiddenError):
            self.service.assign_courier(order_id=1, courier_id=3)

    def test_courier_already_busy(self):
        self.service.assign_courier(order_id=1, courier_id=2)

        with self.assertRaises(ValueError):
            self.service.assign_courier(order_id=2, courier_id=2)

    def test_complete_delivery_marks_order_delivered(self):
        delivery_id = self.service.assign_courier(order_id=1, courier_id=2)

        self.service.complete_delivery(delivery_id)

        self.assertEqual(memory_db.deliveries[delivery_id].status, "completed")
        self.assertEqual(memory_db.orders[1].status, "delivered")

    def test_complete_twice(self):
        delivery_id = self.service.assign_courier(order_id=1, courier_id=2)
        self.service.complete_delivery(delivery_id)

        with self.assertRaises(ValueError):
            self.service.complete_delivery(delivery_id)

    def test_complete_not_found(self):
        with self.assertRaises(NotFoundError):
            self.service.complete_delivery(99)
