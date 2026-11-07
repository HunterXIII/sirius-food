"""Публикация сохранённых событий. При сбое брокера запись остаётся в outbox."""
import asyncio

from app.core.rabbitmq import publish_event
from app.database import SessionLocal
from app.models import OutboxEvent


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
        await asyncio.wait_for(publish_event(event.routing_key, event.payload), timeout=15)
        event.published = True
        order_id = event.payload["order_id"]
        routing_key = event.routing_key
    print(f"[Outbox] Опубликовано {routing_key}: order_id={order_id}", flush=True)
    return True


async def main() -> None:
    print("[Outbox] Ждём неопубликованные события...", flush=True)
    while True:
        try:
            if await publish_next():
                continue
        except Exception as error:
            print(f"[Outbox] Отправка не удалась, повторим позже: {error}", flush=True)
        await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
