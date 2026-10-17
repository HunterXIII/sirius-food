"""
Транспортный слой модуля пользователей.
Техническая валидация, сборка слоёв и перевод исключений в HTTP-статусы.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.dependencies import get_current_user, require_role
from app.database import get_db
from app.exceptions import NotFoundError, ForbiddenError, AccessDeniedError
from app.schemas import UserCreate, RoleUpdate
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

    if len(payload.password) < 8:
        raise HTTPException(
            status_code=400,
            detail="Пароль должен быть не короче 8 символов",
        )

    service = UserService(get_user_repository(db))

    try:
        user = service.register(
            email=payload.email,
            password=payload.password,
            phone=payload.phone,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "status": "success",
        "user_id": user.id,
        "email": user.email,
    }


@router.post("/{user_id}/topup")
def top_up_balance(
    user_id: int,
    amount: float,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Техническая проверка: сумма должна быть положительным числом.
    if amount <= 0:
        raise HTTPException(
            status_code=400,
            detail="Сумма пополнения должна быть положительной",
        )

    service = UserService(get_user_repository(db))

    try:
        new_balance = service.top_up(
            user_id=user_id,
            amount=amount,
            current_user=current_user,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (AccessDeniedError, ForbiddenError) as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "success", "new_balance": new_balance}


@router.patch("/{user_id}/role")
def change_user_role(
    user_id: int,
    payload: RoleUpdate,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    service = UserService(get_user_repository(db))

    try:
        service.change_role(user_id=user_id, role=payload.role)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "success", "user_id": user_id, "role": payload.role}
