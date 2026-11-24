"""Общая топология RabbitMQ и публикация с подтверждением брокера."""
import json

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message
from opentelemetry.trace import SpanKind

from app.core.config import settings
from app.core.correlation import CORRELATION_HEADER
from app.core.order_tracing import extract_parent, order_tracer, propagator

EXCHANGE_NAME = "sirius_events"
DLX_NAME = "dlx_exchange"
BINDINGS = {
    "kitchen": ("order.paid", "order.cancelled"),
    "delivery": ("order.paid",),
    "orders": ("delivery.failed",),
}


async def get_connection():
    return await aio_pika.connect_robust(settings.RABBITMQ_URL, timeout=5)


async def declare_topology(channel):
    exchange = await channel.declare_exchange(EXCHANGE_NAME, ExchangeType.TOPIC, durable=True)
    dlx = await channel.declare_exchange(DLX_NAME, ExchangeType.DIRECT, durable=True)
    for name, routing_keys in BINDINGS.items():
        dlq = await channel.declare_queue(f"{name}_dlq", durable=True)
        await dlq.bind(dlx, routing_key=f"{name}.dlq")
        queue = await channel.declare_queue(
            f"{name}_queue",
            durable=True,
            arguments={
                "x-dead-letter-exchange": DLX_NAME,
                "x-dead-letter-routing-key": f"{name}.dlq",
            },
        )
        for routing_key in routing_keys:
            await queue.bind(exchange, routing_key=routing_key)
    return exchange


async def publish_event(routing_key: str, payload: dict) -> None:
    correlation_id = payload.get("correlation_id")
    headers = {CORRELATION_HEADER: correlation_id} if correlation_id else {}
    with order_tracer.start_as_current_span(
        "RabbitMQ.publish", context=extract_parent(payload.get("traceparent")), kind=SpanKind.PRODUCER,
        attributes={"messaging.system": "rabbitmq", "routing_key": routing_key, "order_id": payload["order_id"]},
        record_exception=False,
    ) as span:
        if correlation_id:
            span.set_attribute("correlation_id", correlation_id)
        propagator.inject(headers)
        # Одноразовое подключение: при сбое outbox повторит отправку позже.
        connection = await aio_pika.connect(settings.RABBITMQ_URL, timeout=5)
        async with connection:
            channel = await connection.channel(publisher_confirms=True, on_return_raises=True)
            # Очереди существуют до первой публикации, даже если consumer ещё не запущен.
            exchange = await declare_topology(channel)
            await exchange.publish(
                Message(
                    body=json.dumps(payload, ensure_ascii=False).encode(),
                    content_type="application/json",
                    message_id=payload["event_id"],
                    headers=headers,
                    delivery_mode=DeliveryMode.PERSISTENT,
                ),
                routing_key=routing_key,
                mandatory=True,
                timeout=5,
            )
