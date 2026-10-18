# locustfile.py
# Нагрузочный тест: много студентов одновременно открывают меню.
# Запуск: locust -f locustfile.py --host=http://127.0.0.1:8000
from locust import HttpUser, task, between


class MenuUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task
    def get_menu(self):
        # GET /menu/items публичный, токен не нужен.
        self.client.get("/menu/items")
