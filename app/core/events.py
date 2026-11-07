"""События оплаты и компенсации. При повторной отправке event_id не меняется."""
from uuid import uuid4


def order_paid(order_id: int, customer_id: int, amount: float) -> dict:
    return {
        "event_id": str(uuid4()),
        "order_id": order_id,
        "customer_id": customer_id,
        "amount": amount,
    }


def delivery_failed(order_id: int, customer_id: int, payment_event_id: str, reason: str) -> dict:
    return {
        "event_id": str(uuid4()),
        "order_id": order_id,
        "customer_id": customer_id,
        "payment_event_id": payment_event_id,
        "reason": reason,
    }


def order_cancelled(order_id: int, customer_id: int, reason: str) -> dict:
    return {
        "event_id": str(uuid4()),
        "order_id": order_id,
        "customer_id": customer_id,
        "reason": reason,
    }
