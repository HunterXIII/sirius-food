"""
Слой бизнес-логики модуля аутентификации.
Здесь нет импортов fastapi и sqlalchemy.
"""
from datetime import datetime, timedelta, timezone

from app.core.jwt import create_access_token, create_refresh_token, REFRESH_TOKEN_EXPIRE_DAYS
from app.core.security import verify_password, hash_token
from app.modules.auth.repository import AuthRepository


class InvalidCredentialsError(Exception):
    """Неверный email или пароль."""


class AuthService:
    """Проверка учётных данных и выдача токенов."""

    def __init__(self, repository: AuthRepository):
        self.repository = repository

    def login(self, email: str, password: str) -> dict:
        """Проверяет учётные данные и возвращает пару токенов."""
        user = self.repository.get_by_email(email)
        # Одна и та же ошибка для "нет пользователя" и "неверный пароль",
        # чтобы по ответу нельзя было узнать, какие email зарегистрированы.
        if not user or not verify_password(password, user.password_hash):
            raise InvalidCredentialsError()

        access_token = create_access_token(user.id)
        refresh_token = create_refresh_token(user.id)

        # Сохраняем refresh-токен в БД для возможности отзыва.
        # В БД кладём только хеш токена.
        self.repository.save_refresh_token(
            user_id=user.id,
            token_hash=hash_token(refresh_token),
            expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        )

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
        }
