from locust import HttpUser, between, events, task


@events.init_command_line_parser.add_listener
def add_order_options(parser):
    parser.add_argument("--menu-item-id", env_var="LOCUST_MENU_ITEM_ID", type=int, default=1)
    parser.add_argument("--order-token", env_var="LOCUST_ORDER_TOKEN", is_secret=True)


class SiriusUser(HttpUser):
    wait_time = between(1, 3)
    menu_wait_time = between(0.1, 0.5)

    def on_start(self):
        # Сценарий ЛР № 4 запускается без учётных данных.
        if not self.environment.parsed_options.order_token:
            self.tasks = [type(self).get_menu]
            self.wait_time = self.menu_wait_time

    @task(7)
    def get_menu(self):
        self.client.get("/menu/items")

    @task(2)
    def get_menu_item(self):
        item_id = self.environment.parsed_options.menu_item_id
        self.client.get(f"/menu/items/{item_id}", name="/menu/items/{id}")

    @task(1)
    def create_order(self):
        options = self.environment.parsed_options
        self.client.post(
            "/orders/create",
            headers={"Authorization": f"Bearer {options.order_token}"},
            json={"item_id": options.menu_item_id, "quantity": 1},
        )
