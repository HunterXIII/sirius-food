"""
Транспортный слой модуля пользователей.
Техническая валидация, сборка слоёв и перевод исключений в HTTP-статусы.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.exceptions import NotFoundError, ForbiddenError
from app.schemas import UserCreate
from app.modules.users.repository import get_user_repository
from app.modules.users.service import UserService

router = APIRouter()


@router.post("/register")
def register_user(payload: UserCreate, db: Session = Depends(get_db)):
    # Формат email уже проверил Pydantic (EmailStr).
    # Техническая проверка формата телефона.
    if payload.phone and len(payload.phone) < 10:
        raise HTTPException(
            status_code=400,
            detail="Некорректный формат номера телефона",
        )

    service = UserService(get_user_repository(db))

    try:
        user = service.register(email=payload.email, phone=payload.phone)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "status": "success",
        "user_id": user.id,
        "email": user.email,
    }


@router.post("/{user_id}/topup")
def top_up_balance(user_id: int, amount: float, db: Session = Depends(get_db)):
    # Техническая проверка: сумма должна быть положительным числом.
    if amount <= 0:
        raise HTTPException(
            status_code=400,
            detail="Сумма пополнения должна быть положительной",
        )

    service = UserService(get_user_repository(db))

    try:
        new_balance = service.top_up(user_id=user_id, amount=amount)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "success", "new_balance": new_balance}
