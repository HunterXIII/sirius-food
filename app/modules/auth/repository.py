"""
Инфраструктурный слой модуля аутентификации.
Поиск пользователя по email и хранение refresh-токенов.
"""
from abc import ABC, abstractmethod
from datetime import datetime

from sqlalchemy.orm import Session

from app import memory_db
from app.core.config import settings
from app.models import User, RefreshToken


class AuthRepository(ABC):
    """Абстрактный интерфейс репозитория аутентификации."""

    @abstractmethod
    def get_by_email(self, email: str):
        """Найти пользователя по email. Если нет - вернуть None."""

    @abstractmethod
    def save_refresh_token(self, user_id: int, token_hash: str, expires_at: datetime) -> None:
        """Сохранить хеш нового refresh-токена."""


class PostgresAuthRepository(AuthRepository):
    """Реализация для PostgreSQL через SQLAlchemy ORM."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_email(self, email: str):
        return self.db.query(User).filter(User.email == email).first()

    def save_refresh_token(self, user_id: int, token_hash: str, expires_at: datetime) -> None:
        self.db.add(RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            is_revoked=False,
        ))
        self.db.commit()


class InMemoryAuthRepository(AuthRepository):
    """Реализация, которая хранит данные в памяти (app/memory_db.py)."""

    def get_by_email(self, email: str):
        for user in memory_db.users.values():
            if user.email == email:
                return user
        return None

    def save_refresh_token(self, user_id: int, token_hash: str, expires_at: datetime) -> None:
        token_id = len(memory_db.refresh_tokens) + 1
        memory_db.refresh_tokens[token_id] = memory_db.RefreshTokenRecord(
            id=token_id,
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            is_revoked=False,
        )


def get_auth_repository(db: Session) -> AuthRepository:
    """Выбор реализации репозитория по настройке REPOSITORY."""
    if settings.REPOSITORY == "memory":
        return InMemoryAuthRepository()
    return PostgresAuthRepository(db)
