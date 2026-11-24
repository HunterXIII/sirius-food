"""Публикация сохранённых событий. При сбое брокера запись остаётся в outbox."""
import asyncio

import structlog

from app.core.logging import setup_logging
from app.core.order_tracing import setup_order_tracing
from app.core.rabbitmq import publish_event
from app.database import SessionLocal
from app.models import OutboxEvent

logger = structlog.get_logger(service="outbox")


async def publish_next() -> bool:
    with SessionLocal.begin() as db:
        event = (
            db.query(OutboxEvent)
            .filter_by(published=False)
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .with_for_update(skip_locked=True)
            .first()
        )
        if event is None:
            return False
        fields = {
            "order_id": event.payload["order_id"],
            "event_id": event.id,
            "routing_key": event.routing_key,
            "correlation_id": event.payload.get("correlation_id"),
        }
        try:
            await asyncio.wait_for(publish_event(event.routing_key, event.payload), timeout=15)
        except Exception:
            logger.warning("publish_failed", **fields)
            raise
        event.published = True
    logger.info("event_published", **fields)
    return True


async def main() -> None:
    setup_logging()
    setup_order_tracing("outbox")
    logger.info("outbox_started")
    while True:
        try:
            if await publish_next():
                continue
        except Exception as error:
            logger.warning("outbox_retry", error_type=type(error).__name__)
        await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
