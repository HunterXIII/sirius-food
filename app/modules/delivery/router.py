"""
Транспортный слой модуля доставки.
Сборка слоёв, вызов сервиса и перевод исключений в HTTP-статусы.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.dependencies import get_current_user, require_role
from app.database import get_db
from app.exceptions import NotFoundError, ForbiddenError, AccessDeniedError
from app.schemas import DeliveryAssign, DeliveryResponse
from app.modules.delivery.repository import get_delivery_repository
from app.modules.delivery.service import DeliveryService

router = APIRouter()


@router.post("/assign")
def assign_courier(
    payload: DeliveryAssign,
    # Курьера на заказ назначает администратор.
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    service = DeliveryService(get_delivery_repository(db))

    try:
        delivery_id = service.assign_courier(
            order_id=payload.order_id,
            courier_id=payload.courier_id,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "success", "delivery_id": delivery_id}


@router.get("/{delivery_id}", response_model=DeliveryResponse)
def get_delivery(
    delivery_id: int,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = DeliveryService(get_delivery_repository(db))

    try:
        return service.get_delivery(delivery_id, current_user)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except AccessDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.patch("/{delivery_id}/complete")
def complete_delivery(
    delivery_id: int,
    current_user=Depends(require_role("courier")),
    db: Session = Depends(get_db),
):
    service = DeliveryService(get_delivery_repository(db))

    try:
        service.complete_delivery(delivery_id, current_user)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except AccessDeniedError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "success"}
