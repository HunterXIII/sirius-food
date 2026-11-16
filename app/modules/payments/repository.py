from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.exceptions import NotFoundError
from app.models import Delivery, MenuItem, Order, Payment, Refund
from app.modules.orders.amounts import order_total


class PaymentConflict(Exception):
    pass


def reserve_payment(
    db: Session, user_id: int, order_id: int, key: str, expected: Decimal | None, return_url: str,
) -> str:
    order = db.scalar(
        select(Order).where(Order.id == order_id, Order.user_id == user_id).with_for_update()
    )
    if order is None:
        raise NotFoundError("Заказ не найден")

    previous = db.scalar(select(Payment).filter_by(user_id=user_id, idempotency_key=key))
    if previous is not None:
        return check_request(previous, order_id, expected)
    if order.status != "processing":
        raise PaymentConflict("Этот заказ нельзя оплатить")

    active = db.scalar(select(Payment.id).where(
        Payment.order_id == order.id, Payment.status != "canceled",
    ))
    if active is not None:
        raise PaymentConflict("Для заказа уже есть платёж. Повторите исходный запрос с тем же ключом.")

    item = db.get(MenuItem, order.item_id)
    if item is None:
        raise NotFoundError("Блюдо не найдено")
    if not item.is_available:
        raise PaymentConflict("Блюдо недоступно")

    amount = order.total_amount
    if amount is None:
        # Неоплаченный заказ, созданный до миграции, ещё не имеет зафиксированной цены.
        try:
            amount = order_total(item.price, order.quantity)
        except ValueError as error:
            raise PaymentConflict(str(error)) from error
    if expected is not None and expected != amount:
        raise PaymentConflict("Указанная сумма отличается от суммы заказа")

    payment_id = str(uuid4())
    inserted = db.scalar(
        insert(Payment).values(
            id=payment_id, user_id=user_id, order_id=order.id, idempotency_key=key,
            amount=amount, expected_amount=expected, return_url=return_url,
        )
        .on_conflict_do_nothing(index_elements=["user_id", "idempotency_key"])
        .returning(Payment.id)
    )
    if inserted is None:
        previous = db.scalars(select(Payment).filter_by(user_id=user_id, idempotency_key=key)).one()
        return check_request(previous, order_id, expected)

    order.total_amount = amount
    return payment_id


def check_request(payment: Payment, order_id: int, expected: Decimal | None) -> str:
    if payment.order_id != order_id or payment.expected_amount != expected:
        raise PaymentConflict("Этот ключ уже использован с другими параметрами")
    return payment.id


def payment_view(db: Session, user_id: int, payment_id: str):
    row = db.execute(
        select(Payment, Order, Refund)
        .join(Order, Payment.order_id == Order.id)
        .outerjoin(Refund, Refund.payment_id == Payment.id)
        .where(Payment.id == payment_id, Payment.user_id == user_id)
    ).one_or_none()
    if row is None:
        raise NotFoundError("Платёж не найден")

    payment, order, refund = row
    delivery = db.scalar(
        select(Delivery).filter_by(order_id=order.id).order_by(Delivery.id.desc()).limit(1)
    )
    return payment, order, refund, delivery
