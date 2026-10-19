"""
Периодическая задача: её раз в минуту ставит в очередь Celery Beat
(расписание - beat_schedule в app/core/celery_app.py).
"""
from datetime import date

from app.core.celery_app import celery_app
from app.core.redis import redis_client
from app.database import SessionLocal
from app.modules.orders.repository import get_order_repository
from app.modules.orders.service import OrderService


@celery_app.task
def update_orders_stats() -> str:
    """Считает заказы за сегодня и кладёт число в Redis: stats:orders:<дата>."""
    today = date.today()

    # Задача - точка входа, как роутер: сама открывает сессию БД
    # и собирает слои (репозиторий -> сервис). Сам SQL-запрос - в репозитории.
    db = SessionLocal()
    try:
        count = OrderService(get_order_repository(db)).count_orders_by_day(today)
    finally:
        db.close()

    redis_client.set(f"stats:orders:{today}", count)
    return f"Orders for {today}: {count}"
