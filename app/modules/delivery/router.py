"""
Транспортный слой модуля доставки.
Сборка слоёв, вызов сервиса и перевод исключений в HTTP-статусы.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.exceptions import NotFoundError, ForbiddenError
from app.schemas import DeliveryAssign
from app.modules.delivery.repository import get_delivery_repository
from app.modules.delivery.service import DeliveryService

router = APIRouter()


@router.post("/assign")
def assign_courier(payload: DeliveryAssign, db: Session = Depends(get_db)):
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


@router.patch("/{delivery_id}/complete")
def complete_delivery(delivery_id: int, db: Session = Depends(get_db)):
    service = DeliveryService(get_delivery_repository(db))

    try:
        service.complete_delivery(delivery_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "success"}
