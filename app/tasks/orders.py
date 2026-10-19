"""
Фоновые задачи по заказу: PDF-чек, email и SMS.
Выполняются воркером Celery, а не процессом FastAPI.
Настоящих PDF и рассылок в проекте нет, тяжёлую работу имитирует time.sleep.

Идемпотентность: после выполнения задача ставит в Redis флаг
"<что сделано>:<order_id>" на час. Если задача с тем же заказом придёт ещё раз
(ретрай, повторная доставка, ручной запуск), она увидит флаг и ничего не сделает.
"""
import time

from app.core.celery_app import celery_app, TaskWithDLQ
from app.core.redis import redis_client


@celery_app.task(bind=True, base=TaskWithDLQ)
def generate_order_pdf(self, order_id: int) -> str:
    """Генерация PDF-чека с проверкой идемпотентности."""
    # Ключ идемпотентности
    key = f"pdf_generated:{order_id}"

    # Если ключ уже есть — PDF уже сгенерирован, пропускаем
    if redis_client.exists(key):
        return f"PDF already generated for order {order_id}"

    time.sleep(2)

    # Сохраняем флаг на 1 час
    redis_client.setex(key, 3600, "1")

    return f"PDF generated for order {order_id}"


# Email и SMS - внешние сервисы, они бывают временно недоступны.
# При любой ошибке задача повторяется до 3 раз с экспоненциальной задержкой.
@celery_app.task(
    base=TaskWithDLQ,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def send_order_email(order_id: int, email: str) -> str:
    """Отправка email о создании заказа, с ретраями и идемпотентностью."""
    key = f"email_sent:{order_id}"
    if redis_client.exists(key):
        return f"Email already sent for order {order_id}"

    time.sleep(1)
    # Имитация падения почтового сервиса для каждого 5-го заказа
    if order_id % 5 == 0:
        raise Exception("Email service unavailable")

    redis_client.setex(key, 3600, "1")
    return f"Email sent to {email} for order {order_id}"


@celery_app.task(
    base=TaskWithDLQ,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def send_order_sms(order_id: int, phone: str) -> str:
    """Отправка SMS о создании заказа, с ретраями и идемпотентностью."""
    key = f"sms_sent:{order_id}"
    if redis_client.exists(key):
        return f"SMS already sent for order {order_id}"

    time.sleep(1)

    redis_client.setex(key, 3600, "1")
    return f"SMS sent to {phone} for order {order_id}"
