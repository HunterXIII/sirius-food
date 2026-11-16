from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.dependencies import require_role
from app.database import SessionLocal
from app.exceptions import NotFoundError
from app.models import Payment
from app.modules.payments.repository import PaymentConflict, payment_view, reserve_payment
from app.modules.payments.service import GatewayMismatch, PaymentService
from app.modules.payments.yookassa import (
    GatewayError, GatewayId, configured, configured_gateway, gateway_client,
)

router = APIRouter()
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=64, pattern=r"^[!-~]+$")]


class PaymentCreate(BaseModel):
    order_id: int = Field(gt=0)
    amount: Decimal | None = Field(
        default=None, gt=0, max_digits=12, decimal_places=2,
        description="Ожидаемая сумма. Сервер сверит её с суммой заказа.",
    )


class RefundResponse(BaseModel):
    id: UUID
    status: str
    amount: Decimal
    reason: str | None


class PaymentResponse(BaseModel):
    id: UUID
    order_id: int
    status: str
    order_status: str
    cancellation_reason: str | None
    delivery_id: int | None
    delivery_status: str | None
    amount: Decimal
    currency: str
    reason: str | None
    confirmation_url: str | None
    refund: RefundResponse | None


class NotificationObject(BaseModel):
    id: GatewayId


class Notification(BaseModel):
    type: Literal["notification"]
    event: Literal["payment.succeeded", "payment.canceled", "refund.succeeded"]
    object: NotificationObject


def read_payment(payment_id: str, user_id: int) -> PaymentResponse:
    with SessionLocal() as db:
        payment, order, refund, delivery = payment_view(db, user_id, payment_id)
        return PaymentResponse(
            id=payment.id, order_id=order.id, status=payment.status, order_status=order.status,
            cancellation_reason=order.cancellation_reason,
            delivery_id=delivery.id if delivery else None,
            delivery_status=delivery.status if delivery else None,
            amount=payment.amount, currency=payment.currency, reason=payment.reason,
            confirmation_url=payment.confirmation_url if payment.status == "pending" else None,
            refund=RefundResponse(id=refund.id, status=refund.status, amount=refund.amount, reason=refund.reason)
            if refund else None,
        )


@router.post("", response_model=PaymentResponse, responses={202: {"model": PaymentResponse}})
def create_payment(
    payload: PaymentCreate, idempotency_key: Key, response: Response,
    current_user=Depends(require_role("student")),
):
    if not configured() or settings.REPOSITORY != "postgres":
        raise HTTPException(503, "Оплата через ЮKassa временно недоступна")

    user_id = current_user.id
    try:
        with SessionLocal.begin() as db:
            payment_id = reserve_payment(
                db, user_id, payload.order_id, idempotency_key, payload.amount, settings.YOOKASSA_RETURN_URL,
            )
    except NotFoundError as error:
        raise HTTPException(404, str(error)) from error
    except PaymentConflict as error:
        raise HTTPException(409, str(error)) from error

    # Обычно первая попытка возвращает ссылку сразу. Если API ЮKassa временно
    # недоступно, фоновый обработчик продолжит работу с той же записью.
    with gateway_client() as client:
        PaymentService(SessionLocal, configured_gateway(client)).process_next(Payment, payment_id)
    result = read_payment(payment_id, user_id)
    if result.status == "creating":
        response.status_code = 202
    return result


@router.get("/{payment_id}", response_model=PaymentResponse)
def get_payment(payment_id: UUID, current_user=Depends(require_role("student"))):
    if settings.REPOSITORY != "postgres":
        raise HTTPException(503, "Для платежей требуется PostgreSQL")
    try:
        return read_payment(str(payment_id), current_user.id)
    except NotFoundError as error:
        raise HTTPException(404, str(error)) from error


@router.post("/webhook", response_class=Response)
def webhook(payload: Notification):
    if not configured() or settings.REPOSITORY != "postgres":
        raise HTTPException(503, "Проверка уведомлений ЮKassa временно недоступна")
    try:
        with gateway_client() as client:
            PaymentService(SessionLocal, configured_gateway(client)).handle_notification(payload.event, payload.object.id)
    except GatewayError as error:
        raise HTTPException(503, "Не удалось проверить уведомление в ЮKassa") from error
    except GatewayMismatch as error:
        raise HTTPException(409, "Данные уведомления не совпадают с платежом") from error
    return Response(status_code=200)
