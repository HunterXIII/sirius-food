"""
Транспортный слой модуля заказов.
Принимает HTTP-запрос, делает техническую проверку, собирает слои,
вызывает сервис и переводит исключения в HTTP-статусы.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.exceptions import NotFoundError
from app.schemas import OrderCreate
from app.modules.orders.repository import get_order_repository
from app.modules.orders.service import OrderService

router = APIRouter()


@router.post("/create")
def create_order(payload: OrderCreate, db: Session = Depends(get_db)):
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
            user_id=payload.user_id,
            item_id=payload.item_id,
            quantity=payload.quantity,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "success", "order_id": order_id}
