"""
Зависимости FastAPI для аутентификации и проверки роли.
Это API-слой: здесь можно HTTPException.
"""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.jwt import decode_token
from app.database import get_db
from app.modules.users.repository import get_user_repository

# Схема извлечения токена из заголовка Authorization: Bearer <token>.
# В Swagger по кнопке Authorize появляется поле, куда вставляется access_token.
# auto_error=False: без заголовка FastAPI вернул бы 403, а нужно 401.
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    """
    Извлекает текущего пользователя из JWT.
    Возбуждает HTTPException 401, если токена нет или он невалиден.
    """
    if credentials is None:
        raise HTTPException(401, "Not authenticated")

    try:
        payload = decode_token(credentials.credentials)
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(401, "Invalid token")

    # Refresh-токен живёт 7 дней, ходить с ним в API нельзя - только access.
    if payload.get("type") != "access":
        raise HTTPException(401, "Invalid token")

    user = get_user_repository(db).get_user_by_id(user_id)
    if not user:
        raise HTTPException(401, "User not found")
    if user.is_blocked:
        raise HTTPException(403, "User is blocked")
    return user


def require_role(*roles: str):
    """
    Dependency для проверки роли пользователя.
    Пропускает, если роль пользователя - одна из roles.
    Возбуждает HTTPException 403, если роль не подходит.
    """
    def checker(current_user=Depends(get_current_user)):
        if current_user.role.name not in roles:
            raise HTTPException(403, "Access denied")
        return current_user
    return checker
