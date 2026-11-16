"""
Слой бизнес-логики модуля меню.
Здесь нет импортов fastapi и sqlalchemy.
"""
from app.exceptions import NotFoundError
from app.modules.menu.repository import MenuRepository, item_to_dict


class MenuService:
    """Бизнес-правила работы с меню столовой."""

    def __init__(self, repository: MenuRepository):
        # Инверсия зависимостей: репозиторий передают через конструктор.
        self.repository = repository

    def get_menu(self) -> list[dict]:
        """Всё меню. Откуда данные (БД или кеш), сервис не знает."""
        return self.repository.get_all_items()

    def get_item(self, item_id: int) -> dict:
        """Данные одного блюда для витрины."""
        item = self.repository.get_item_by_id(item_id)
        if item is None:
            raise NotFoundError("Блюдо не найдено")
        return item_to_dict(item)

    def get_category(self, category_id: int) -> dict:
        """Категория с её блюдами. NotFoundError - категории нет."""
        category = self.repository.get_category(category_id)
        if category is None:
            raise NotFoundError("Категория не найдена")
        return category

    def create_item(self, name: str, price: float, category_id: int | None = None) -> int:
        """
        Добавление блюда в меню. Возвращает id блюда.
        ValueError - блюдо с таким названием уже есть.
        NotFoundError - указана несуществующая категория.
        """
        if self.repository.get_item_by_name(name):
            raise ValueError("Блюдо с таким названием уже существует")
        if category_id is not None:
            self.get_category(category_id)

        # Новое блюдо сразу доступно для заказа.
        item_id = self.repository.save_item(
            name=name, price=price, is_available=True, category_id=category_id
        )
        # Инвалидация кеша: меню изменилось
        self.repository.invalidate_cache()
        return item_id

    def update_item(
        self,
        item_id: int,
        name: str | None = None,
        price: float | None = None,
        is_available: bool | None = None,
        category_id: int | None = None,
    ) -> int:
        """
        Изменение блюда: меняются только переданные поля (не None).
        Возвращает id блюда. NotFoundError - нет блюда или категории.
        """
        item = self.repository.get_item_by_id(item_id)
        if not item:
            raise NotFoundError("Блюдо не найдено")
        if category_id is not None:
            self.get_category(category_id)

        if name is not None:
            item.name = name
        if price is not None:
            item.price = price
        if is_available is not None:
            item.is_available = is_available
        if category_id is not None:
            item.category_id = category_id

        self.repository.update_item(item)
        # Инвалидация кеша: меню изменилось
        self.repository.invalidate_cache()
        return item.id
