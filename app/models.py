"""
Определение ORM-моделей предметной области «Сириус.Еда».
"""
from datetime import datetime, timezone

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Index, Integer,
    JSON, Numeric, String, Text, UniqueConstraint, text,
)
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    """Пользователь системы."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False)
    phone = Column(String, nullable=True)
    balance = Column(Float, default=0.0)
    is_blocked = Column(Boolean, default=False)
    # Хеш пароля (bcrypt). Сам пароль нигде не хранится.
    password_hash = Column(String, nullable=False)
    # Ссылка на роль.
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)

    role = relationship("Role")


class Role(Base):
    """Роль пользователя: student, cook, courier, admin."""
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)


class RefreshToken(Base):
    """Refresh-токен для обновления access-токена."""
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    # Храним хеш токена, а не сам токен — на случай утечки БД.
    token_hash = Column(String, unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    is_revoked = Column(Boolean, default=False)


class Category(Base):
    """Категория меню: супы, горячее, напитки и т.д."""
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)


class MenuItem(Base):
    __tablename__ = "menu_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    is_available = Column(Boolean, default=True)
    # Категория необязательна: у блюд, созданных до lab4, её нет.
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    item_id = Column(Integer, ForeignKey("menu_items.id"))
    quantity = Column(Integer, nullable=False)
    status = Column(String, default="processing")
    total_amount = Column(Numeric(12, 2))
    correlation_id = Column(String(128), nullable=True)
    traceparent = Column(String(55), nullable=True)
    cancellation_reason = Column(Text)
    # Время создания (lab5, для статистики). Ставит SQLAlchemy при INSERT.
    # У заказов, созданных до lab5, его нет.
    created_at = Column(DateTime, default=datetime.now, nullable=True)

    user = relationship("User")
    item = relationship("MenuItem")


class Delivery(Base):
    __tablename__ = "deliveries"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    courier_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String, default="pending")

    order = relationship("Order")
    courier = relationship("User")


class KitchenOrder(Base):
    """Заказ, который кухня получила через RabbitMQ."""
    __tablename__ = "kitchen_orders"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), unique=True, nullable=False)
    status = Column(String, default="pending", nullable=False)


class ProcessedEvent(Base):
    """У каждого consumer свой список обработанных событий."""
    __tablename__ = "processed_events"

    consumer = Column(String(50), primary_key=True)
    id = Column(String(36), primary_key=True)


class OutboxEvent(Base):
    """Событие сохраняется вместе с локальным шагом, публикуется отдельным воркером."""
    __tablename__ = "outbox"

    id = Column(String(36), primary_key=True)
    routing_key = Column(String(100), nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    published = Column(Boolean, default=False, nullable=False, index=True)


def utcnow():
    return datetime.now(timezone.utc)


class GatewayOperation:
    id = Column(String(36), primary_key=True)
    gateway_id = Column(String(64), unique=True)
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="RUB")
    status = Column(String(20), nullable=False, default="creating")
    reason = Column(String(80))
    attempts = Column(Integer, nullable=False, default=0)
    first_sent_at = Column(DateTime(timezone=True))
    next_check_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class Payment(GatewayOperation, Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_payments_user_key"),
        Index(
            "uq_payments_open_or_paid_order", "order_id", unique=True,
            postgresql_where=text("status <> 'canceled'"),
            sqlite_where=text("status <> 'canceled'"),
        ),
        CheckConstraint("amount > 0", name="ck_payments_positive_amount"),
    )

    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    idempotency_key = Column(String(64), nullable=False)
    expected_amount = Column(Numeric(12, 2))
    return_url = Column(Text, nullable=False)
    confirmation_url = Column(Text)
    paid_event_id = Column(String(36), unique=True)


class Refund(GatewayOperation, Base):
    __tablename__ = "refunds"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_refunds_positive_amount"),)

    payment_id = Column(String(36), ForeignKey("payments.id"), nullable=False, unique=True)


class AssistantDocument(Base):
    __tablename__ = "assistant_documents"

    source_key = Column(String(100), primary_key=True)
    search_text = Column(String, nullable=False)
    embedding = Column(VECTOR(384).with_variant(JSON(), "sqlite"), nullable=False)


class AssistantChat(Base):
    __tablename__ = "assistant_chats"

    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)


class AssistantReply(Base):
    __tablename__ = "assistant_replies"
    __table_args__ = (
        Index("ix_assistant_replies_user_created", "user_id", "created_at", "id"),
        Index("ix_assistant_replies_chat_created", "chat_id", "created_at", "id"),
    )

    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    chat_id = Column(String(36), ForeignKey("assistant_chats.id", name="fk_assistant_replies_chat"))
    helpful = Column(Boolean)
    phoenix_span_id = Column(String(16))
    message = Column(Text)
    answer = Column(Text)
    mode = Column(String(20))
    sources = Column(JSON)
    created_at = Column(DateTime(timezone=True))
