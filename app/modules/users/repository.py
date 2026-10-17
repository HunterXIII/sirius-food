"""
Инфраструктурный слой модуля пользователей.
Только этот файл знает, где и как хранятся пользователи.
Бизнес-правил здесь нет.
"""
from abc import ABC, abstractmethod

from sqlalchemy.orm import Session

from app import memory_db
from app.core.config import settings
from app.models import User


class UserRepository(ABC):
    """Абстрактный интерфейс репозитория пользователей."""

    @abstractmethod
    def get_user_by_id(self, user_id: int):
        """Найти пользователя по id. Если нет - вернуть None."""

    @abstractmethod
    def get_user_by_email(self, email: str):
        """Найти пользователя по email. Если нет - вернуть None."""

    @abstractmethod
    def save_user(self, email: str, phone: str | None, balance: float, is_blocked: bool):
        """Сохранить нового пользователя и вернуть его."""

    @abstractmethod
    def update_user_balance(self, user, new_balance: float) -> None:
        """Сохранить новый баланс пользователя."""


class PostgresUserRepository(UserRepository):
    """Реализация для PostgreSQL через SQLAlchemy ORM."""

    def __init__(self, db: Session):
        self.db = db

    def get_user_by_id(self, user_id: int):
        return self.db.query(User).filter(User.id == user_id).first()

    def get_user_by_email(self, email: str):
        return self.db.query(User).filter(User.email == email).first()

    def save_user(self, email: str, phone: str | None, balance: float, is_blocked: bool):
        new_user = User(
            email=email,
            phone=phone,
            balance=balance,
            is_blocked=is_blocked,
        )
        self.db.add(new_user)
        self.db.commit()
        self.db.refresh(new_user)
        return new_user

    def update_user_balance(self, user, new_balance: float) -> None:
        user.balance = new_balance
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)


class InMemoryUserRepository(UserRepository):
    """Реализация, которая хранит данные в памяти (app/memory_db.py)."""

    def get_user_by_id(self, user_id: int):
        return memory_db.users.get(user_id)

    def get_user_by_email(self, email: str):
        for user in memory_db.users.values():
            if user.email == email:
                return user
        return None

    def save_user(self, email: str, phone: str | None, balance: float, is_blocked: bool):
        user_id = len(memory_db.users) + 1
        new_user = memory_db.UserRecord(
            id=user_id,
            email=email,
            phone=phone,
            balance=balance,
            is_blocked=is_blocked,
        )
        memory_db.users[user_id] = new_user
        return new_user

    def update_user_balance(self, user, new_balance: float) -> None:
        memory_db.users[user.id].balance = new_balance


def get_user_repository(db: Session) -> UserRepository:
    """
    Выбор реализации репозитория по настройке REPOSITORY.
    Хранилище меняется здесь, а service.py и router.py остаются как есть.
    """
    if settings.REPOSITORY == "memory":
        return InMemoryUserRepository()
    return PostgresUserRepository(db)
