"""
Слой бизнес-логики модуля меню.
Здесь нет импортов fastapi и sqlalchemy.
"""
from app.exceptions import NotFoundError
from app.modules.menu.repository import MenuRepository


class MenuService:
    """Бизнес-правила работы с меню столовой."""

    def __init__(self, repository: MenuRepository):
        # Инверсия зависимостей: репозиторий передают через конструктор.
        self.repository = repository

    def create_item(self, name: str, price: float) -> int:
        """
        Добавление блюда в меню. Возвращает id блюда.
        ValueError - блюдо с таким названием уже есть.
        """
        if self.repository.get_item_by_name(name):
            raise ValueError("Блюдо с таким названием уже существует")

        # Новое блюдо сразу доступно для заказа.
        return self.repository.save_item(name=name, price=price, is_available=True)

    def update_item(
        self,
        item_id: int,
        name: str | None = None,
        price: float | None = None,
        is_available: bool | None = None,
    ) -> int:
        """
        Изменение блюда: меняются только переданные поля (не None).
        Возвращает id блюда. NotFoundError - блюда нет.
        """
        item = self.repository.get_item_by_id(item_id)
        if not item:
            raise NotFoundError("Блюдо не найдено")

        if name is not None:
            item.name = name
        if price is not None:
            item.price = price
        if is_available is not None:
            item.is_available = is_available

        self.repository.update_item(item)
        return item.id
