"""
Хеширование паролей и токенов.
"""
import hashlib

from passlib.context import CryptContext

# Контекст для хеширования. bcrypt — современный алгоритм с солью.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Возвращает bcrypt-хеш пароля."""
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Проверяет соответствие пароля хешу."""
    return pwd_context.verify(plain, hashed)


def hash_token(token: str) -> str:
    """
    SHA-256 от токена: так refresh-токены хранятся в БД.
    bcrypt тут не подходит: токен надо искать в БД по хешу, а bcrypt
    каждый раз даёт новый хеш (соль). Подбирать токен перебором бессмысленно,
    он длинный и случайный, поэтому медленный bcrypt не нужен.
    """
    return hashlib.sha256(token.encode()).hexdigest()
