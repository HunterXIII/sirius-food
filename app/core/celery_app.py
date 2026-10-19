"""
Настройка Celery. Брокер и хранилище результатов - Redis.
Запуск воркера: celery -A app.core.celery_app worker --loglevel=info
"""
from celery import Celery

from app.core.config import settings

# Создаём приложение Celery.
# Брокер (Redis) — сюда FastAPI ставит задачи.
# Backend (Redis) — сюда сохраняются результаты выполнения.
celery_app = Celery(
    "sirius_food",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    # Модули с задачами. Воркер запускается с -A app.core.celery_app и импортирует
    # только этот файл. Без include он не знает задач и пишет "unregistered task".
    include=["app.tasks.orders"],
)

# Настройки сериализации: JSON вместо pickle (безопаснее).
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)
