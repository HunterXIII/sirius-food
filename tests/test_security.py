"""
Тесты безопасности через HTTP (FastAPI TestClient).
PostgreSQL не нужен: репозитории переключаются на in-memory.
Нужен Redis для rate limiting: docker compose up -d redis
Запуск: python -m unittest discover tests -v
"""
import unittest

from fastapi.testclient import TestClient

from app import memory_db
from app.core.config import settings
from app.core.jwt import create_refresh_token
from app.core.rate_limit import redis_client
from app.core.security import hash_password
from app.main import app

# Все репозитории - в памяти. Фабрики get_*_repository читают
# эту настройку на каждом запросе, поэтому её можно поменять здесь.
settings.REPOSITORY = "memory"

PASSWORD = "password123"
# bcrypt медленный, поэтому хеш считаем один раз на все тесты.
PASSWORD_HASH = hash_password(PASSWORD)

client = TestClient(app)


def add_user(user_id, email, role="student", balance=0.0):
    """Положить пользователя с паролем PASSWORD прямо в memory_db."""
    role_id = next(r.id for r in memory_db.roles.values() if r.name == role)
    memory_db.users[user_id] = memory_db.UserRecord(
        id=user_id,
        email=email,
        phone=None,
        balance=balance,
        is_blocked=False,
        password_hash=PASSWORD_HASH,
        role_id=role_id,
    )


def login(email):
    """Войти через /auth/login и вернуть пару токенов."""
    response = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return response.json()


def auth(email):
    """Заголовок Authorization с access-токеном пользователя."""
    return {"Authorization": f"Bearer {login(email)['access_token']}"}


class SecurityTest(unittest.TestCase):
    def setUp(self):
        memory_db.clear()
        # Сбросить счётчики rate limiting, иначе тесты мешают друг другу.
        for key in redis_client.scan_iter("rate_limit:*"):
            redis_client.delete(key)

        # Студенты 1 и 2, повар 3, курьеры 4 и 5.
        add_user(1, "ivan@sirius.ru", balance=1000)
        add_user(2, "petr@sirius.ru", balance=1000)
        add_user(3, "cook@sirius.ru", role="cook")
        add_user(4, "courier@sirius.ru", role="courier")
        add_user(5, "courier2@sirius.ru", role="courier")
        memory_db.menu_items[1] = memory_db.MenuItemRecord(
            id=1, name="Борщ", price=200.0, is_available=True
        )

    # ---------- 401: нет токена или токен не тот

    def test_no_token_401(self):
        response = client.post("/orders/create", json={"item_id": 1, "quantity": 1})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(memory_db.orders, {})

    def test_invalid_token_401(self):
        headers = {"Authorization": "Bearer not-a-jwt"}

        response = client.post("/orders/create", json={"item_id": 1, "quantity": 1}, headers=headers)

        self.assertEqual(response.status_code, 401)

    def test_refresh_token_instead_of_access_401(self):
        # Refresh-токен подписан тем же ключом, но ходить с ним в API нельзя.
        headers = {"Authorization": f"Bearer {create_refresh_token(1)}"}

        response = client.post("/orders/create", json={"item_id": 1, "quantity": 1}, headers=headers)

        self.assertEqual(response.status_code, 401)

    def test_wrong_password_401(self):
        response = client.post("/auth/login", json={"email": "ivan@sirius.ru", "password": "wrong-pass"})

        self.assertEqual(response.status_code, 401)

    # ---------- 403: роль не подходит

    def test_student_cannot_see_kitchen_403(self):
        response = client.get("/orders/kitchen/orders", headers=auth("ivan@sirius.ru"))

        self.assertEqual(response.status_code, 403)

    def test_cook_sees_kitchen(self):
        client.post("/orders/create", json={"item_id": 1, "quantity": 1}, headers=auth("ivan@sirius.ru"))

        response = client.get("/orders/kitchen/orders", headers=auth("cook@sirius.ru"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)

    def test_cook_cannot_create_order_403(self):
        response = client.post(
            "/orders/create", json={"item_id": 1, "quantity": 1}, headers=auth("cook@sirius.ru")
        )

        self.assertEqual(response.status_code, 403)

    def test_student_cannot_change_menu_403(self):
        response = client.post(
            "/menu/items", json={"name": "Компот", "price": 50}, headers=auth("ivan@sirius.ru")
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(memory_db.menu_items), 1)

    # ---------- 403: чужой объект (IDOR)

    def test_cancel_foreign_order_403(self):
        client.post("/orders/create", json={"item_id": 1, "quantity": 1}, headers=auth("ivan@sirius.ru"))

        response = client.post("/orders/1/cancel", headers=auth("petr@sirius.ru"))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(memory_db.orders[1].status, "processing")

    def test_topup_foreign_balance_403(self):
        response = client.post("/users/1/topup?amount=100", headers=auth("petr@sirius.ru"))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(memory_db.users[1].balance, 1000)

    def test_foreign_delivery_403(self):
        memory_db.orders[1] = memory_db.OrderRecord(
            id=1, user_id=1, item_id=1, quantity=1, status="paid"
        )
        memory_db.deliveries[1] = memory_db.DeliveryRecord(
            id=1, order_id=1, courier_id=4, status="in_progress"
        )

        # Свои: курьер доставки и студент, чей заказ.
        self.assertEqual(client.get("/delivery/1", headers=auth("courier@sirius.ru")).status_code, 200)
        self.assertEqual(client.get("/delivery/1", headers=auth("ivan@sirius.ru")).status_code, 200)
        # Чужие: другой курьер и другой студент.
        self.assertEqual(client.get("/delivery/1", headers=auth("courier2@sirius.ru")).status_code, 403)
        self.assertEqual(client.get("/delivery/1", headers=auth("petr@sirius.ru")).status_code, 403)
        # Завершить чужую доставку тоже нельзя.
        response = client.patch("/delivery/1/complete", headers=auth("courier2@sirius.ru"))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(memory_db.deliveries[1].status, "in_progress")

    def test_order_is_created_for_token_owner(self):
        # Даже если клиент пришлёт чужой user_id, заказ оформится на владельца токена.
        response = client.post(
            "/orders/create",
            json={"user_id": 2, "item_id": 1, "quantity": 1},
            headers=auth("ivan@sirius.ru"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(memory_db.orders[1].user_id, 1)
        self.assertEqual(memory_db.users[1].balance, 800)
        self.assertEqual(memory_db.users[2].balance, 1000)

    # ---------- 429: rate limiting

    def test_login_rate_limit_429(self):
        codes = []
        for _ in range(6):
            response = client.post(
                "/auth/login", json={"email": "ivan@sirius.ru", "password": "wrong-pass"}
            )
            codes.append(response.status_code)

        # 5 попыток проходят (неверный пароль - 401), шестая блокируется.
        self.assertEqual(codes, [401, 401, 401, 401, 401, 429])

    # ---------- Refresh Token rotation

    def test_refresh_gives_new_pair(self):
        tokens = login("ivan@sirius.ru")

        response = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})

        self.assertEqual(response.status_code, 200)
        new_tokens = response.json()
        self.assertNotEqual(new_tokens["refresh_token"], tokens["refresh_token"])
        # С новым access-токеном API работает.
        headers = {"Authorization": f"Bearer {new_tokens['access_token']}"}
        self.assertEqual(client.post("/users/1/topup?amount=1", headers=headers).status_code, 200)

    def test_refresh_reuse_resets_session(self):
        old = login("ivan@sirius.ru")
        new = client.post("/auth/refresh", json={"refresh_token": old["refresh_token"]}).json()

        # Старый refresh-токен пришёл второй раз (например, его украли).
        reuse = client.post("/auth/refresh", json={"refresh_token": old["refresh_token"]})
        self.assertEqual(reuse.status_code, 401)

        # Сброшена вся сессия: новый refresh-токен тоже больше не работает.
        response = client.post("/auth/refresh", json={"refresh_token": new["refresh_token"]})
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
