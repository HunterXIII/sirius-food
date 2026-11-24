from datetime import timedelta, timezone
import logging
from random import uniform

import structlog
from sqlalchemy import select

from app.core.events import order_paid
from app.models import Order, OutboxEvent, Payment, Refund, utcnow
from app.modules.payments.yookassa import GatewayError, GatewayPayment, GatewayRefund

logger = logging.getLogger("uvicorn.error")
event_logger = structlog.get_logger(service="payments")
RETRY_DELAYS = (1, 2, 4, 8)
LEASE = timedelta(seconds=90)
POST_WINDOW = timedelta(hours=23)
POLL_INTERVAL = timedelta(seconds=15)
TERMINAL = ("succeeded", "canceled")


class GatewayMismatch(Exception):
    pass


def lock_row(db, model, row_id):
    return db.scalar(select(model).where(model.id == row_id).with_for_update())


class PaymentService:
    def __init__(self, sessions, gateway):
        self.sessions = sessions
        self.gateway = gateway

    def claim(self, model, operation_id=None):
        now = utcnow()
        with self.sessions.begin() as db:
            query = select(model).where(model.next_check_at <= now)
            if operation_id is not None:
                query = query.where(model.id == operation_id)
            job = db.scalar(query.order_by(model.next_check_at).limit(1).with_for_update(skip_locked=True))
            if job is None:
                return None

            if job.gateway_id is None:
                expired = (
                    job.first_sent_at is not None
                    and now - job.first_sent_at.replace(tzinfo=timezone.utc) >= POST_WINDOW
                )
                if expired or job.attempts >= len(RETRY_DELAYS) + 1:
                    reason = "idempotency_window_elapsed" if expired else "retry_limit"
                    self.flag_for_review(job, reason)
                    return None
                job.first_sent_at = job.first_sent_at or now

            job.next_check_at = now + LEASE
            job.attempts += 1
            db.flush()
            db.expunge(job)
            return job

    def process_next(self, model, operation_id=None) -> bool:
        job = self.claim(model, operation_id)
        if job is None:
            return False

        # Work was claimed and committed before contacting the gateway.
        try:
            if model is Payment:
                remote = (
                    self.gateway.get_payment(job.gateway_id) if job.gateway_id
                    else self.gateway.create_payment(job)
                )
                self.apply_payment(remote, local_id=job.id)
            else:
                with self.sessions() as db:
                    gateway_payment_id = db.get(Payment, job.payment_id).gateway_id
                remote = (
                    self.gateway.get_refund(job.gateway_id) if job.gateway_id
                    else self.gateway.create_refund(job, gateway_payment_id)
                )
                self.apply_refund(remote, local_id=job.id)
        except GatewayError as error:
            self.record_error(model, job, error)
        except GatewayMismatch:
            self.record_error(model, job, GatewayError("gateway_data_mismatch", retryable=False))
        return True

    def record_error(self, model, job, error: GatewayError):
        with self.sessions.begin() as db:
            current = lock_row(db, model, job.id)
            if current.attempts != job.attempts or current.status in TERMINAL:
                return
            # A webhook may have already moved a write with an unknown outcome to pending.
            if current.gateway_id and not job.gateway_id:
                return

            current.reason = error.reason
            if current.gateway_id and error.retryable:
                delay = RETRY_DELAYS[min(current.attempts - 1, len(RETRY_DELAYS) - 1)]
            elif not current.gateway_id and error.retryable and current.attempts <= len(RETRY_DELAYS):
                delay = RETRY_DELAYS[current.attempts - 1]
            else:
                self.flag_for_review(current, error.reason)
                return

            current.next_check_at = utcnow() + timedelta(seconds=delay * uniform(0.8, 1.2))
            logger.warning("yookassa_retry operation=%s id=%s attempt=%s reason=%s",
                           model.__tablename__, current.id, current.attempts, current.reason)

    @staticmethod
    def flag_for_review(operation, reason):
        operation.status = "needs_review"
        operation.reason = reason
        operation.next_check_at = None
        logger.error("yookassa_review operation=%s id=%s reason=%s",
                     operation.__tablename__, operation.id, reason)

    def apply_payment(self, remote: GatewayPayment, local_id: str | None = None):
        paid_event = None
        with self.sessions.begin() as db:
            candidate = db.scalar(select(Payment).filter_by(gateway_id=remote.id))
            if candidate is None:
                candidate = db.get(Payment, remote.metadata.get("payment_id", ""))
            if candidate is None and local_id is None:
                return
            if candidate is None or (local_id is not None and candidate.id != local_id):
                raise GatewayMismatch()

            # Lock in the same order as payment reservation and delivery compensation.
            order = lock_row(db, Order, candidate.order_id)
            payment = db.scalar(
                select(Payment).where(Payment.id == candidate.id)
                .execution_options(populate_existing=True).with_for_update()
            )
            if (
                payment.gateway_id not in (None, remote.id)
                or payment.first_sent_at is None
                or remote.metadata.get("payment_id") != payment.id
                or remote.metadata.get("order_id") != str(order.id)
                or remote.amount.value != payment.amount
                or remote.amount.currency != payment.currency
                or remote.status not in (*TERMINAL, "pending", "waiting_for_capture")
                or (remote.status == "succeeded" and not remote.paid)
            ):
                raise GatewayMismatch()

            if payment.status in TERMINAL:
                return
            if remote.confirmation is not None:
                url = remote.confirmation.confirmation_url
                if url and url.startswith("https://"):
                    payment.confirmation_url = url

            previous = payment.status
            self.apply_status(payment, remote)
            if remote.status == "succeeded":
                if order.status != "processing":
                    raise GatewayMismatch()
                order.status = "paid"
                paid_event = order_paid(
                    order.id, order.user_id, float(payment.amount), order.correlation_id, order.traceparent,
                )
                payment.paid_event_id = paid_event["event_id"]
                db.add(OutboxEvent(id=paid_event["event_id"], routing_key="order.paid", payload=paid_event))
            if previous != payment.status:
                logger.info("yookassa_payment id=%s order_id=%s status=%s", payment.id, order.id, payment.status)
        if paid_event is not None:
            event_logger.info(
                "order_paid",
                order_id=paid_event["order_id"],
                event_id=paid_event["event_id"],
                correlation_id=paid_event["correlation_id"],
            )

    def apply_refund(self, remote: GatewayRefund, local_id: str | None = None):
        with self.sessions.begin() as db:
            refund = db.scalars(
                select(Refund)
                .join(Payment, Refund.payment_id == Payment.id)
                .where(Payment.gateway_id == remote.payment_id)
                .with_for_update(of=Refund)
            ).one_or_none()
            if refund is None and local_id is None:
                return
            if refund is None:
                raise GatewayMismatch()
            if (
                (local_id is not None and refund.id != local_id)
                or refund.gateway_id not in (None, remote.id)
                or refund.first_sent_at is None
                or remote.amount.value != refund.amount
                or remote.amount.currency != refund.currency
                or remote.status not in (*TERMINAL, "pending")
            ):
                raise GatewayMismatch()

            if refund.status in TERMINAL:
                return
            previous = refund.status
            self.apply_status(refund, remote)
            if previous != refund.status:
                logger.info("yookassa_refund id=%s payment_id=%s status=%s", refund.id, refund.payment_id, refund.status)
                if refund.status == "canceled":
                    logger.error("yookassa_refund_rejected id=%s reason=%s", refund.id, refund.reason)

    @staticmethod
    def apply_status(operation, remote):
        operation.gateway_id = remote.id
        operation.status = "pending" if remote.status == "waiting_for_capture" else remote.status
        operation.reason = remote.cancellation_details.reason if remote.cancellation_details else None
        if remote.status == "waiting_for_capture":
            operation.reason = "unexpected_waiting_for_capture"
        operation.next_check_at = None if operation.status in TERMINAL else utcnow() + POLL_INTERVAL

    def handle_notification(self, event: str, gateway_id: str):
        expected_status = event.split(".", 1)[1]
        try:
            if event == "refund.succeeded":
                remote = self.gateway.get_refund(gateway_id)
                if remote.id != gateway_id:
                    raise GatewayMismatch()
                if remote.status == expected_status:
                    self.apply_refund(remote)
            else:
                remote = self.gateway.get_payment(gateway_id)
                if remote.id != gateway_id:
                    raise GatewayMismatch()
                if remote.status == expected_status:
                    self.apply_payment(remote)
        except GatewayError as error:
            if error.status_code != 404:
                raise
