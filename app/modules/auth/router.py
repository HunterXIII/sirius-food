"""
Транспортный слой модуля аутентификации.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.core.rate_limit import rate_limit
from app.database import get_db
from app.modules.auth.repository import get_auth_repository
from app.modules.auth.service import AuthService, InvalidCredentialsError, InvalidTokenError

router = APIRouter()


class LoginSchema(BaseModel):
    """Схема запроса на вход."""
    email: EmailStr
    password: str


class RefreshSchema(BaseModel):
    """Схема запроса на обновление токена."""
    refresh_token: str


# Не больше 5 попыток входа в минуту с одного IP - защита от перебора паролей.
@router.post("/auth/login", dependencies=[Depends(rate_limit(5, 60))])
def login(payload: LoginSchema, db: Session = Depends(get_db)):
    """Аутентификация пользователя и выдача пары токенов."""
    service = AuthService(get_auth_repository(db))
    try:
        return service.login(payload.email, payload.password)
    except InvalidCredentialsError:
        raise HTTPException(401, "Invalid email or password")


@router.post("/auth/refresh")
def refresh(payload: RefreshSchema, db: Session = Depends(get_db)):
    """Обмен refresh-токена на новую пару токенов (старый refresh отзывается)."""
    service = AuthService(get_auth_repository(db))
    try:
        return service.refresh(payload.refresh_token)
    except InvalidTokenError:
        raise HTTPException(401, "Invalid refresh token")
