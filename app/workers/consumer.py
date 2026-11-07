"""Consumer'ы кухни, доставки и заказов. Локальные шаги Saga сохраняются с outbox."""
import asyncio
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import exists
from sqlalchemy.dialects.postgresql import insert

from app.core.events import delivery_failed, order_cancelled
from app.core.rabbitmq import BINDINGS, declare_topology, get_connection
from app.database import SessionLocal
from app.models import Delivery, KitchenOrder, Order, OutboxEvent, ProcessedEvent, Role, User


class OrderEvent(BaseModel):
    event_id: UUID
    order_id: int = Field(strict=True, gt=0)
    customer_id: int = Field(strict=True, gt=0)


class OrderPaid(OrderEvent):
    amount: float = Field(ge=0, allow_inf_nan=False)


class DeliveryFailed(OrderEvent):
    payment_event_id: UUID
    reason: str


class OrderCancelled(OrderEvent):
    reason: str


EVENT_SCHEMAS = {
    "order.paid": OrderPaid,
    "delivery.failed": DeliveryFailed,
    "order.cancelled": OrderCancelled,
}


def process_kitchen(db, order, routing_key: str) -> str:
    cancelled = routing_key == "order.cancelled" or order.status == "cancelled"
    statement = insert(KitchenOrder).values(
        order_id=order.id, status="cancelled" if cancelled else "pending",
    )
    if cancelled:
        statement = statement.on_conflict_do_update(
            index_elements=["order_id"], set_={"status": "cancelled"},
        )
    else:
        # Поздний OrderPaid не должен перезаписать уже полученную отмену.
        statement = statement.on_conflict_do_nothing(index_elements=["order_id"])
    db.execute(statement)
    return f"Отменён заказ {order.id}" if cancelled else f"Принят заказ {order.id}"


def process_delivery(db, order, payload: OrderPaid) -> str:
    if order.status != "paid":
        return f"Заказ {order.id} уже не ожидает доставки"
    delivery = db.query(Delivery).filter_by(order_id=order.id).first()
    if delivery is not None and delivery.status != "pending":
        return f"Доставка для заказа {order.id} уже обработана"
    if delivery is None:
        delivery = Delivery(order_id=order.id)
        db.add(delivery)

    busy = exists().where(Delivery.courier_id == User.id, Delivery.status == "in_progress")
    courier = (
        db.query(User).join(Role)
        .filter(Role.name == "courier", User.is_blocked.is_(False), ~busy)
        .order_by(User.id)
        .with_for_update(of=User, skip_locked=True)
        .first()
    )
    if courier is not None:
        delivery.courier_id = courier.id
        delivery.status = "in_progress"
        return f"Заказ {order.id}: назначен курьер {courier.id}"

    delivery.status = "failed"
    event = delivery_failed(order.id, order.user_id, str(payload.event_id), "Свободный курьер не найден")
    db.add(OutboxEvent(id=event["event_id"], routing_key="delivery.failed", payload=event))
    return f"Заказ {order.id}: курьер не найден, сохранён DeliveryFailed"


def compensate_payment(db, order, payload: DeliveryFailed) -> str:
    # Статус под блокировкой защищает и от нового event_id для той же неудачи.
    if order.status != "paid":
        return f"Компенсация для заказа {order.id} не требуется: {order.status}"
    payment = db.get(OutboxEvent, str(payload.payment_event_id))
    if payment is None or payment.routing_key != "order.paid":
        raise ValueError("Исходное событие оплаты не найдено")
    paid = OrderPaid.model_validate(payment.payload)
    if paid.order_id != order.id or paid.customer_id != order.user_id:
        raise ValueError("Событие оплаты относится к другому заказу")
    user = db.query(User).filter_by(id=order.user_id).populate_existing().with_for_update().one()
    user.balance += paid.amount
    order.status = "cancelled"
    event = order_cancelled(order.id, order.user_id, payload.reason)
    db.add(OutboxEvent(id=event["event_id"], routing_key="order.cancelled", payload=event))
    return f"Заказ {order.id} отменён, возврат {paid.amount} пользователю {user.id}"


def save_event(payload: OrderEvent, consumer: str, routing_key: str) -> str | None:
    with SessionLocal.begin() as db:
        # PK (consumer, id) защищает и от двух одновременных копий события.
        event_id = db.execute(
            insert(ProcessedEvent)
            .values(consumer=consumer, id=str(payload.event_id))
            .on_conflict_do_nothing()
            .returning(ProcessedEvent.id)
        ).scalar_one_or_none()
        if event_id is None:
            return None
        order = db.query(Order).filter_by(id=payload.order_id).with_for_update().first()
        if order is None or order.user_id != payload.customer_id:
            raise ValueError("В событии указан неизвестный заказ или неверный владелец")
        if consumer == "kitchen":
            result = process_kitchen(db, order, routing_key)
        elif consumer == "delivery":
            result = process_delivery(db, order, payload)
        else:
            result = compensate_payment(db, order, payload)
    return result


async def process_message(message, consumer: str) -> None:
    try:
        # При ошибке reject без requeue: одна попытка, затем DLQ.
        # ACK отправляется только после успешного коммита БД.
        async with message.process(requeue=False):
            if message.routing_key not in BINDINGS[consumer]:
                raise ValueError("Неподходящий тип события для consumer")
            payload = EVENT_SCHEMAS[message.routing_key].model_validate_json(message.body)
            result = save_event(payload, consumer, message.routing_key)
            if result is None:
                result = f"Повтор {payload.event_id} пропущен"
            print(f"[{consumer.title()}] {result}", flush=True)
    except Exception as error:
        print(f"[{consumer.title()}] Ошибка обработки: {error}", flush=True)


async def run_consumer(consumer: str) -> None:
    connection = await get_connection()
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=10)
        await declare_topology(channel)
        queue = await channel.get_queue(f"{consumer}_queue")

        async def callback(message):
            await process_message(message, consumer)

        await queue.consume(callback)
        print(f"[{consumer.title()}] Ждём события: {', '.join(BINDINGS[consumer])}...", flush=True)
        await asyncio.Future()
