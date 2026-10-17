"""
Слой бизнес-логики модуля аутентификации.
Здесь нет импортов fastapi и sqlalchemy.
"""
from datetime import datetime, timedelta, timezone

from jose import JWTError

from app.core.jwt import (
    create_access_token,
    create_refresh_token,
    decode_token,
    REFRESH_TOKEN_EXPIRE_DAYS,
)
from app.core.security import verify_password, hash_token
from app.modules.auth.repository import AuthRepository


class InvalidCredentialsError(Exception):
    """Неверный email или пароль."""


class InvalidTokenError(Exception):
    """Refresh-токен невалиден, просрочен или уже использован."""


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

        return self._create_tokens(user.id)

    def refresh(self, refresh_token: str) -> dict:
        """
        Refresh Token rotation: по refresh-токену выдаёт новую пару токенов,
        а старый refresh-токен отзывает. Каждый refresh-токен - одноразовый.
        InvalidTokenError - токен невалиден, просрочен или уже использован.
        """
        try:
            payload = decode_token(refresh_token)
        except JWTError:
            raise InvalidTokenError()
        if payload.get("type") != "refresh":
            raise InvalidTokenError()

        token = self.repository.get_refresh_token(hash_token(refresh_token))
        if token is None:
            raise InvalidTokenError()

        if token.is_revoked:
            # Токен уже был использован. Значит, его украли (или клиент
            # отправил его дважды). Не знаем, у кого настоящий, поэтому
            # отзываем все refresh-токены пользователя: войти придётся заново.
            self.repository.revoke_all_user_tokens(token.user_id)
            raise InvalidTokenError()

        self.repository.revoke_refresh_token(token)
        return self._create_tokens(token.user_id)

    def _create_tokens(self, user_id: int) -> dict:
        """Создаёт пару токенов и сохраняет refresh-токен."""
        access_token = create_access_token(user_id)
        refresh_token = create_refresh_token(user_id)

        # Сохраняем refresh-токен в БД для возможности отзыва.
        # В БД кладём только хеш токена.
        self.repository.save_refresh_token(
            user_id=user_id,
            token_hash=hash_token(refresh_token),
            expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        )

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
        }
