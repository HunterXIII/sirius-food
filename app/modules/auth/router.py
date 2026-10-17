"""
Транспортный слой модуля аутентификации.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.auth.repository import get_auth_repository
from app.modules.auth.service import AuthService, InvalidCredentialsError

router = APIRouter()


class LoginSchema(BaseModel):
    """Схема запроса на вход."""
    email: EmailStr
    password: str


@router.post("/auth/login")
def login(payload: LoginSchema, db: Session = Depends(get_db)):
    """Аутентификация пользователя и выдача пары токенов."""
    service = AuthService(get_auth_repository(db))
    try:
        return service.login(payload.email, payload.password)
    except InvalidCredentialsError:
        raise HTTPException(401, "Invalid email or password")
