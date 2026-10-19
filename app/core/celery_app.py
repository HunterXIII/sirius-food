"""
Настройка Celery. Брокер и хранилище результатов - Redis.
Запуск воркера: celery -A app.core.celery_app worker -Q default --loglevel=info
"""
from celery import Celery, Task
from celery.utils.log import get_task_logger
from kombu import Exchange, Queue

from app.core.config import settings

logger = get_task_logger(__name__)

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

# Две очереди: default - обычные задачи, dlq (Dead Letter Queue) - задачи,
# которые так и не выполнились после всех ретраев.
# В Redis каждая очередь - это список с тем же именем (redis-cli lrange dlq 0 -1).
celery_app.conf.task_queues = (
    Queue("default", Exchange("default"), routing_key="default"),
    Queue("dlq", Exchange("dlq"), routing_key="dlq"),
)

celery_app.conf.task_default_queue = "default"
celery_app.conf.task_default_exchange = "default"
celery_app.conf.task_default_routing_key = "default"


class TaskWithDLQ(Task):
    """
    Базовый класс задачи с Dead Letter Queue.
    Сама Celery на Redis не умеет перекладывать упавшие задачи в другую очередь,
    поэтому делаем это в on_failure: Celery вызывает его, когда задача упала
    окончательно (ретраи кончились). Ретрай - это не failure, тут он не вызывается.
    """

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        # Кладём в dlq ту же задачу с теми же аргументами. Воркер слушает только
        # очередь default (-Q default), поэтому в dlq она лежит, пока её не разберут.
        self.apply_async(args=args, kwargs=kwargs, queue="dlq")
        logger.error("Задача %s[%s] отправлена в DLQ: %r", self.name, task_id, exc)
