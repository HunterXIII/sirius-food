"""
Фоновые задачи по заказу: PDF-чек, email и SMS.
Выполняются воркером Celery, а не процессом FastAPI.
Настоящих PDF и рассылок в проекте нет, тяжёлую работу имитирует time.sleep.
"""
import time

from app.core.celery_app import celery_app


@celery_app.task
def generate_order_pdf(order_id: int) -> str:
    """
    Генерация PDF-чека для заказа.
    Имитация тяжёлой операции через time.sleep.
    """
    time.sleep(2)
    return f"PDF generated for order {order_id}"


@celery_app.task
def send_order_email(order_id: int, email: str) -> str:
    """Отправка email о создании заказа."""
    time.sleep(1)
    return f"Email sent to {email} for order {order_id}"


@celery_app.task
def send_order_sms(order_id: int, phone: str) -> str:
    """Отправка SMS о создании заказа."""
    time.sleep(1)
    return f"SMS sent to {phone} for order {order_id}"
