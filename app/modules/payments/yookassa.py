"""Server-side access to the YooKassa v3 API."""

from decimal import Decimal
from typing import Annotated

import httpx
from pydantic import BaseModel, Field, StringConstraints, ValidationError

from app.core.config import settings

GatewayId = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]{1,64}$")]


class Money(BaseModel):
    value: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str


class Cancellation(BaseModel):
    reason: str = Field(max_length=80)


class Confirmation(BaseModel):
    confirmation_url: str | None = None


class GatewayPayment(BaseModel):
    id: GatewayId
    amount: Money
    status: str
    paid: bool
    metadata: dict[str, str] = Field(default_factory=dict)
    confirmation: Confirmation | None = None
    cancellation_details: Cancellation | None = None


class GatewayRefund(BaseModel):
    id: GatewayId
    payment_id: GatewayId
    amount: Money
    status: str
    cancellation_details: Cancellation | None = None


class GatewayError(Exception):
    def __init__(self, reason: str, *, retryable: bool = True, status_code: int | None = None):
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable
        self.status_code = status_code


class YooKassa:
    def __init__(self, client: httpx.Client, shop_id: str, secret: str):
        self.client = client
        self.auth = (shop_id, secret)

    def _request(self, method, path, schema, *, key=None, payload=None):
        try:
            response = self.client.request(
                method, path, auth=self.auth,
                headers={"Idempotence-Key": key} if key else {},
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise GatewayError("timeout") from exc
        except httpx.RequestError as exc:
            raise GatewayError("network_error") from exc

        code = response.status_code
        if not response.is_success:
            if code >= 500 or code in (408, 429):
                raise GatewayError(f"gateway_http_{code}", status_code=code)
            # A rejected request isn't proof that a previous timed-out write failed.
            raise GatewayError(f"gateway_http_{code}", retryable=False, status_code=code)
        try:
            return schema.model_validate_json(response.content)
        except ValidationError as exc:
            raise GatewayError("invalid_gateway_response") from exc

    def create_payment(self, payment):
        return self._request("POST", "payments", GatewayPayment, key=payment.id, payload={
            "amount": {"value": f"{payment.amount:.2f}", "currency": payment.currency},
            "capture": True,
            "confirmation": {"type": "redirect", "return_url": payment.return_url},
            "description": f"Заказ №{payment.order_id}",
            "metadata": {"payment_id": payment.id, "order_id": str(payment.order_id)},
        })

    def get_payment(self, gateway_id: str):
        return self._request("GET", f"payments/{gateway_id}", GatewayPayment)

    def create_refund(self, refund, gateway_payment_id: str):
        return self._request("POST", "refunds", GatewayRefund, key=refund.id, payload={
            "amount": {"value": f"{refund.amount:.2f}", "currency": refund.currency},
            "payment_id": gateway_payment_id,
        })

    def get_refund(self, gateway_id: str):
        return self._request("GET", f"refunds/{gateway_id}", GatewayRefund)


def configured() -> bool:
    return bool(settings.YOOKASSA_SHOP_ID and settings.YOOKASSA_SECRET_KEY.get_secret_value())


def gateway_client():
    return httpx.Client(
        base_url="https://api.yookassa.ru/v3/",
        timeout=httpx.Timeout(15.0, connect=4.0),
        follow_redirects=False,
    )


def configured_gateway(client: httpx.Client) -> YooKassa:
    return YooKassa(client, settings.YOOKASSA_SHOP_ID, settings.YOOKASSA_SECRET_KEY.get_secret_value())
