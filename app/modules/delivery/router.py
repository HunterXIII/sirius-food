"""
Транспортный слой модуля доставки.
Сборка слоёв, вызов сервиса и перевод исключений в HTTP-статусы.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
import grpc
from app.core.dependencies import get_current_user, require_role
from app.core.config import settings
from app.exceptions import NotFoundError, ForbiddenError, AccessDeniedError
from app.schemas import DeliveryAssign, DeliveryResponse
from app.modules.delivery.grpc_client import DeliveryGrpcClient, log_delivery_statuses
from app.modules.delivery.repository import InMemoryDeliveryRepository
from app.modules.delivery.service import DeliveryService

router = APIRouter()


def get_delivery_service():
    # Старый режим in-memory используется тестами в одном процессе.
    if settings.REPOSITORY == "memory":
        yield DeliveryService(InMemoryDeliveryRepository())
        return

    with grpc.insecure_channel("127.0.0.1:50051") as channel:
        yield DeliveryGrpcClient(channel)


@router.post("/assign")
def assign_courier(
    payload: DeliveryAssign,
    background_tasks: BackgroundTasks,
    # Курьера на заказ назначает администратор.
    current_user=Depends(require_role("admin")),
    service: DeliveryGrpcClient | DeliveryService = Depends(get_delivery_service),
):
    try:
        delivery_id = service.assign_courier(
            order_id=payload.order_id,
            courier_id=payload.courier_id,
        )
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if settings.REPOSITORY != "memory":
        background_tasks.add_task(log_delivery_statuses, delivery_id, payload.courier_id)

    return {"status": "success", "delivery_id": delivery_id}


@router.get("/{delivery_id}", response_model=DeliveryResponse)
def get_delivery(
    delivery_id: int,
    current_user=Depends(get_current_user),
    service: DeliveryGrpcClient | DeliveryService = Depends(get_delivery_service),
):
    try:
        return service.get_delivery(delivery_id, current_user)
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (AccessDeniedError, ForbiddenError) as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.patch("/{delivery_id}/complete")
def complete_delivery(
    delivery_id: int,
    current_user=Depends(require_role("courier")),
    service: DeliveryGrpcClient | DeliveryService = Depends(get_delivery_service),
):
    try:
        service.complete_delivery(delivery_id, current_user)
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (AccessDeniedError, ForbiddenError) as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "success"}
