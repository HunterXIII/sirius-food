"""Данные для поиска, статус заказов и история чата."""

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, text, tuple_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AssistantChat, AssistantDocument, AssistantReply, Category, Delivery, MenuItem, Order, OutboxEvent
from app.modules.assistant.faq import FAQ
from app.modules.assistant.tracing import record_retrieval


@dataclass(frozen=True)
class Source:
    key: str
    title: str
    facts: str


@dataclass(frozen=True)
class ConversationTurn:
    message: str
    answer: str


ACTIVE_ORDER_STATUSES = ("processing", "paid")


@dataclass(frozen=True)
class OrderDetails:
    id: int
    status: str
    quantity: int
    dish_name: str | None
    delivery_status: str | None
    cancellation_reason: str | None = None

    @property
    def active(self) -> bool:
        return self.status in ACTIVE_ORDER_STATUSES

    @property
    def status_text(self) -> str:
        if self.status == "paid" and self.delivery_status == "in_progress":
            return "в доставке"
        return {
            "processing": "ожидает оплаты",
            "paid": "оплачен",
            "delivered": "доставлен",
            "cancelled": "отменён",
        }.get(self.status, self.status)


def menu_words(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold().replace("ё", "е")))


class AssistantRepository:
    def __init__(self, db: Session):
        self.db = db

    def find_sources(self, question: str, embed, contextual_question: str | None = None) -> list[Source]:
        question_words = f" {menu_words(question)} "
        # Сериализуем обновление общего индекса между запросами.
        self.db.execute(text("LOCK TABLE assistant_documents IN SHARE ROW EXCLUSIVE MODE"))
        menu = self.db.execute(
            select(MenuItem, Category.name).outerjoin(Category, MenuItem.category_id == Category.id)
        ).all()
        sources = {}
        search_texts = {}
        exact_matches = []
        for item, category in menu:
            key = f"menu:{item.id}"
            title = f"{item.name} — {category}" if category else item.name
            availability = "В наличии" if item.is_available else "Нет в наличии"
            sources[key] = Source(key, title, f"Цена {item.price:g} ₽. {availability}.")
            search_texts[key] = title
            name = menu_words(item.name)
            position = question_words.find(f" {name} ")
            if name and position >= 0:
                exact_matches.append((position, -len(name), key))

        # Явно указанное блюдо берём из актуального меню, даже если раньше обсуждали другое.
        if exact_matches:
            self.db.commit()
            matched = [sources[key] for _, _, key in sorted(exact_matches)[:settings.ASSISTANT_MAX_DOCUMENTS]]
            record_retrieval(matched)
            return matched

        (query_vector,) = embed([contextual_question or question], kind="query")
        for slug, (title, facts) in FAQ.items():
            key = f"faq:{slug}"
            sources[key] = Source(key, title, facts)
            search_texts[key] = f"{title} {facts}"

        indexed = dict(self.db.execute(
            select(AssistantDocument.source_key, AssistantDocument.search_text)
        ).all())
        removed = indexed.keys() - search_texts.keys()
        if removed:
            self.db.execute(delete(AssistantDocument).where(AssistantDocument.source_key.in_(removed)))

        changed = [key for key, content in search_texts.items() if indexed.get(key) != content]
        if changed:
            vectors = embed([search_texts[key] for key in changed], kind="passage")
            for key, vector in zip(changed, vectors, strict=True):
                self.db.merge(AssistantDocument(
                    source_key=key, search_text=search_texts[key], embedding=vector,
                ))
            self.db.flush()

        distance = AssistantDocument.embedding.cosine_distance(query_vector)
        rows = self.db.execute(
            select(AssistantDocument.source_key, distance)
            .where(distance <= settings.ASSISTANT_MAX_COSINE_DISTANCE)
            .order_by(distance, AssistantDocument.source_key)
            .limit(settings.ASSISTANT_MAX_DOCUMENTS)
        ).all()
        # Освобождаем транзакцию до обращения к внешней модели.
        self.db.commit()
        matched = [sources[key] for key, _ in rows]
        record_retrieval(matched, [float(value) for _, value in rows])
        return matched

    def get_orders(self, user_id: int, order_id: int | None = None) -> list[OrderDetails]:
        delivery_status = (
            select(Delivery.status)
            .where(Delivery.order_id == Order.id)
            .order_by(Delivery.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        query = (
            select(Order.id, Order.status, Order.quantity, MenuItem.name, delivery_status)
            .outerjoin(MenuItem, MenuItem.id == Order.item_id)
            .where(Order.user_id == user_id)
            .order_by(Order.id.desc())
        )
        if order_id is None:
            active = self.db.execute(query.where(Order.status.in_(ACTIVE_ORDER_STATUSES))).all()
            if active:
                return [OrderDetails(*row) for row in active]
        else:
            query = query.where(Order.id == order_id)
        order = self.db.execute(query.limit(1)).first()
        if order is None:
            return []

        reason = None
        if order.status == "cancelled":
            reason = self.db.scalar(
                select(OutboxEvent.payload["reason"].as_string())
                .where(
                    OutboxEvent.routing_key == "order.cancelled",
                    OutboxEvent.payload["order_id"].as_integer() == order.id,
                    OutboxEvent.payload["customer_id"].as_integer() == user_id,
                )
                .order_by(OutboxEvent.created_at.desc(), OutboxEvent.id.desc())
                .limit(1)
            )
        return [OrderDetails(*order, cancellation_reason=reason)]

    def ordered_dishes(self, user_id: int) -> list[str]:
        return list(self.db.scalars(
            select(MenuItem.name)
            .join(Order, Order.item_id == MenuItem.id)
            .where(Order.user_id == user_id, Order.status.in_(("paid", "delivered")))
            .group_by(MenuItem.name)
            .order_by(func.max(Order.id).desc())
            .limit(10)
        ))

    def last_available_dish(self, user_id: int) -> str | None:
        return self.db.scalar(
            select(MenuItem.name)
            .join(Order, Order.item_id == MenuItem.id)
            .where(
                Order.user_id == user_id,
                Order.status.in_(("paid", "delivered")),
                MenuItem.is_available.is_(True),
            )
            .order_by(Order.id.desc())
            .limit(1)
        )

    def owns_chat(self, user_id: int, chat_id: str) -> bool:
        return self.db.scalar(select(AssistantChat.id).where(
            AssistantChat.id == chat_id,
            AssistantChat.user_id == user_id,
        )) is not None

    def recent_context(self, user_id: int, chat_id: str) -> list[ConversationTurn]:
        rows = self.db.execute(
            select(AssistantReply.message, AssistantReply.answer)
            .where(
                AssistantReply.user_id == user_id,
                AssistantReply.chat_id == chat_id,
                AssistantReply.mode == "rag",
            )
            .order_by(AssistantReply.created_at.desc(), AssistantReply.id.desc())
            .limit(4)
        ).all()
        return [ConversationTurn(message, answer[:1200]) for message, answer in reversed(rows)]

    def save_reply(
        self, reply_id: str, user_id: int, *, chat_id: str, new_chat: bool,
        message: str, answer: str, mode: str, sources: list[Source], phoenix_span_id: str | None = None,
    ):
        if new_chat:
            self.db.add(AssistantChat(id=chat_id, user_id=user_id))
            self.db.flush()
        self.db.add(AssistantReply(
            id=reply_id,
            user_id=user_id,
            chat_id=chat_id,
            phoenix_span_id=phoenix_span_id,
            message=message,
            answer=answer,
            mode=mode,
            sources=[asdict(source) for source in sources],
            created_at=datetime.now(timezone.utc),
        ))
        self.db.commit()

    def get_history(
        self, user_id: int, limit: int, before: str | None, chat_id: str | None = None,
    ) -> list[AssistantReply] | None:
        # У старых записей с оценками нет текста и времени сообщения.
        query = select(AssistantReply).where(
            AssistantReply.user_id == user_id,
            AssistantReply.created_at.is_not(None),
        )
        if chat_id is not None:
            query = query.where(AssistantReply.chat_id == chat_id)
        if before is not None:
            cursor = self.db.scalar(query.where(AssistantReply.id == before))
            if cursor is None:
                return None
            query = query.where(
                tuple_(AssistantReply.created_at, AssistantReply.id) < (cursor.created_at, cursor.id)
            )
        return list(self.db.scalars(
            query.order_by(AssistantReply.created_at.desc(), AssistantReply.id.desc()).limit(limit)
        ))

    def rate_reply(self, reply_id: str, user_id: int, helpful: bool) -> AssistantReply | None:
        reply = self.db.scalar(
            select(AssistantReply).where(AssistantReply.id == reply_id, AssistantReply.user_id == user_id)
        )
        if reply is None:
            return None
        reply.helpful = helpful
        self.db.commit()
        return reply

    def rollback(self):
        self.db.rollback()
