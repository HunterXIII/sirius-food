"""
Слой бизнес-логики модуля пользователей.
Здесь нет импортов fastapi и sqlalchemy.
"""
from app.exceptions import NotFoundError, ForbiddenError
from app.modules.users.repository import UserRepository

# Бизнес-правило: максимальная сумма одного пополнения.
MAX_TOP_UP = 50000


class UserService:
    """Бизнес-правила регистрации и пополнения баланса."""

    def __init__(self, repository: UserRepository):
        # Инверсия зависимостей: репозиторий передают через конструктор.
        self.repository = repository

    def register(self, email: str, phone: str | None):
        """
        Регистрация пользователя. Возвращает созданного пользователя.
        ValueError - email уже занят.
        """
        if self.repository.get_user_by_email(email):
            raise ValueError("Пользователь с таким email уже зарегистрирован")

        # Новый пользователь: нулевой баланс, не заблокирован.
        return self.repository.save_user(
            email=email,
            phone=phone,
            balance=0.0,
            is_blocked=False,
        )

    def top_up(self, user_id: int, amount: float) -> float:
        """
        Пополнение баланса. Возвращает новый баланс.
        NotFoundError - нет пользователя, ForbiddenError - пользователь
        заблокирован, ValueError - сумма больше лимита.
        """
        user = self.repository.get_user_by_id(user_id)
        if not user:
            raise NotFoundError("Пользователь не найден")

        if user.is_blocked:
            raise ForbiddenError("Пользователь заблокирован. Пополнение невозможно")

        if amount > MAX_TOP_UP:
            raise ValueError("Максимальная сумма пополнения — 50000 рублей")

        new_balance = user.balance + amount
        self.repository.update_user_balance(user, new_balance)
        return new_balance
