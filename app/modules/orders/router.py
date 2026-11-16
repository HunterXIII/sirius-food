"""
Транспортный слой модуля заказов.
Принимает HTTP-запрос, проверяет токен и роль, делает техническую проверку,
собирает слои, вызывает сервис и переводит исключения в HTTP-статусы.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.dependencies import require_role
from app.database import get_db
from app.exceptions import NotFoundError
from app.schemas import OrderCreate, OrderResponse
from app.modules.orders.repository import get_order_repository
from app.modules.orders.service import OrderService

router = APIRouter()


@router.post("/create")
def create_order(
    payload: OrderCreate,
    # Заказ может сделать только студент (повар и курьер - нет).
    current_user=Depends(require_role("student")),
    db: Session = Depends(get_db),
):
    # Техническая валидация параметров запроса.
    if payload.quantity <= 0:
        raise HTTPException(
            status_code=400,
            detail="Количество должно быть больше нуля",
        )

    # Сборка слоёв: репозиторий передаётся в сервис.
    service = OrderService(get_order_repository(db))

    # Сам сценарий выполняет сервис, роутер только переводит ошибки в HTTP.
    try:
        order_id = service.create_order(
            # user_id берём из токена, а не из тела запроса.
            user_id=current_user.id,
            item_id=payload.item_id,
            quantity=payload.quantity,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "success", "order_id": order_id}


@router.get("/kitchen/orders", response_model=list[OrderResponse])
def kitchen_orders(
    current_user=Depends(require_role("cook")),
    db: Session = Depends(get_db),
):
    service = OrderService(get_order_repository(db))
    return service.get_kitchen_orders()
