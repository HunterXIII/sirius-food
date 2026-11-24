"""События оплаты и компенсации. При повторной отправке event_id не меняется."""
from uuid import uuid4

NO_COURIER_REASON = "Свободный курьер не найден"


def order_paid(
    order_id: int, customer_id: int, amount: float,
    correlation_id: str | None = None, traceparent: str | None = None,
) -> dict:
    return {
        "event_id": str(uuid4()),
        "order_id": order_id,
        "customer_id": customer_id,
        "amount": amount,
        "correlation_id": correlation_id,
        "traceparent": traceparent,
    }


def delivery_failed(
    order_id: int, customer_id: int, payment_event_id: str, reason: str, correlation_id: str | None = None,
) -> dict:
    return {
        "event_id": str(uuid4()),
        "order_id": order_id,
        "customer_id": customer_id,
        "payment_event_id": payment_event_id,
        "reason": reason,
        "correlation_id": correlation_id,
    }


def order_cancelled(order_id: int, customer_id: int, reason: str, correlation_id: str | None = None) -> dict:
    return {
        "event_id": str(uuid4()),
        "order_id": order_id,
        "customer_id": customer_id,
        "reason": reason,
        "correlation_id": correlation_id,
    }
