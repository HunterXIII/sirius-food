"""
Слой бизнес-логики модуля пользователей.
Здесь нет импортов fastapi и sqlalchemy.
"""
from app.core.security import hash_password
from app.exceptions import NotFoundError, ForbiddenError, AccessDeniedError
from app.modules.users.repository import UserRepository

# Бизнес-правило: максимальная сумма одного пополнения.
MAX_TOP_UP = 50000


class UserService:
    """Бизнес-правила регистрации и пополнения баланса."""

    def __init__(self, repository: UserRepository):
        # Инверсия зависимостей: репозиторий передают через конструктор.
        self.repository = repository

    def register(self, email: str, password: str, phone: str | None):
        """
        Регистрация пользователя. Возвращает созданного пользователя.
        ValueError - email уже занят.
        """
        if self.repository.get_user_by_email(email):
            raise ValueError("Пользователь с таким email уже зарегистрирован")

        # Новый пользователь: нулевой баланс, не заблокирован, роль student.
        # В БД попадает только bcrypt-хеш пароля.
        return self.repository.save_user(
            email=email,
            phone=phone,
            balance=0.0,
            is_blocked=False,
            password_hash=hash_password(password),
            role_id=self.repository.get_role_id("student"),
        )

    def top_up(self, user_id: int, amount: float, current_user) -> float:
        """
        Пополнение баланса. Возвращает новый баланс.
        NotFoundError - нет пользователя, AccessDeniedError - чужой баланс,
        ForbiddenError - пользователь заблокирован, ValueError - сумма больше лимита.
        """
        user = self.repository.get_user_by_id(user_id)
        if not user:
            raise NotFoundError("Пользователь не найден")

        # Защита от IDOR: user_id пришёл в URL, пополнить можно только свой баланс.
        if user.id != current_user.id:
            raise AccessDeniedError("Нельзя пополнить чужой баланс")

        if user.is_blocked:
            raise ForbiddenError("Пользователь заблокирован. Пополнение невозможно")

        if amount > MAX_TOP_UP:
            raise ValueError("Максимальная сумма пополнения — 50000 рублей")

        new_balance = user.balance + amount
        self.repository.update_user_balance(user, new_balance)
        return new_balance

    def change_role(self, user_id: int, role: str) -> None:
        """
        Смена роли пользователя (её делает администратор).
        NotFoundError - нет пользователя, ValueError - нет такой роли.
        """
        user = self.repository.get_user_by_id(user_id)
        if not user:
            raise NotFoundError("Пользователь не найден")

        role_id = self.repository.get_role_id(role)
        if role_id is None:
            raise ValueError("Такой роли нет")

        self.repository.update_user_role(user, role_id)
