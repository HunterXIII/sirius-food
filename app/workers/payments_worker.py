"""Resume YooKassa requests and reconcile pending payments and refunds."""

import logging
from time import monotonic, sleep

from sqlalchemy import func, select

from app.core.logging import setup_logging
from app.database import SessionLocal
from app.models import Payment, Refund
from app.modules.payments.service import PaymentService
from app.modules.payments.yookassa import configured, configured_gateway, gateway_client

logger = logging.getLogger("uvicorn.error")


def log_status_counts():
    with SessionLocal() as db:
        for model in (Payment, Refund):
            counts = dict(db.execute(select(model.status, func.count()).group_by(model.status)).all())
            logger.info("yookassa_counts operation=%s counts=%s", model.__tablename__, counts)


def main():
    setup_logging()
    logging.basicConfig(level=logging.INFO)
    if not configured():
        logger.info("ЮKassa не настроена, обработчик платежей ждёт перезапуска с настройками")
        while True:
            sleep(60)

    with gateway_client() as client:
        service = PaymentService(SessionLocal, configured_gateway(client))
        next_report = monotonic()
        while True:
            try:
                if monotonic() >= next_report:
                    log_status_counts()
                    next_report = monotonic() + 60
                refund_processed = service.process_next(Refund)
                payment_processed = service.process_next(Payment)
                if refund_processed or payment_processed:
                    continue
            except Exception as error:
                logger.error("yookassa_worker_error type=%s", type(error).__name__)
            sleep(0.5)


if __name__ == "__main__":
    main()
