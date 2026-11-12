"""Сценарии чата. Персональные ответы формируются внутри приложения."""

import logging
import re
from dataclasses import dataclass, field
from time import perf_counter
from uuid import uuid4

from app.exceptions import NotFoundError
from app.modules.assistant.embeddings import EmbeddingUnavailableError, embed
from app.modules.assistant.openrouter import OpenRouterClient, OpenRouterError
from app.modules.assistant.repository import AssistantRepository, ConversationTurn, OrderDetails, Source

from app.modules.assistant.tracing import current_span_id, trace_step

logger = logging.getLogger("uvicorn.error.assistant")

ORDER_WORD = re.compile(r"\bзаказ(?:а|е|у|ом|ы|ов|ам|ами|ах)?\b")
ORDER_NUMBER = re.compile(r"\bзаказ(?:а|е|у|ом)?\s*(?:№\s*|#\s*|\s+)([1-9]\d{0,9})(?!\d)")
REPEAT_ORDER = re.compile(r"\bповторить\b")
ORDER_HISTORY = re.compile(r"\b(?:истори[яию]\s+(?:моих\s+)?заказ\w*|заказывал[аи]?)\b")

FOLLOW_UP = re.compile(r"^(?:а\b|и\b|а?\s*можно\s+подробнее\b)|\b(?:он|она|оно|они|его|её|их|этот|это)\b")

NO_DATA = "В меню и справке пока нет данных для ответа на этот вопрос."
UNAVAILABLE = "Ассистент временно недоступен. Попробуйте позже."


@dataclass
class Answer:
    text: str
    mode: str
    sources: list[Source] = field(default_factory=list)


class AssistantService:
    def __init__(self, repository: AssistantRepository, llm: OpenRouterClient):
        self.repository = repository
        self.llm = llm

    def chat(self, message: str, user_id: int, order_id: int | None, chat_id: str | None = None):
        new_chat = chat_id is None
        if chat_id is None:
            chat_id = str(uuid4())
        elif not self.repository.owns_chat(user_id, chat_id):
            raise NotFoundError("Чат не найден")
        started = perf_counter()
        question = message.casefold()
        reply_id = str(uuid4())
        if order_id is None and (number := ORDER_NUMBER.search(question)):
            order_id = int(number.group(1))

        if order_id is None and REPEAT_ORDER.search(question):
            dish = self.repository.last_available_dish(user_id)
            text = f"Вы уже заказывали «{dish}». Хотите повторить?" if dish else (
                "В истории нет блюд, которые сейчас можно заказать повторно."
            )
            answer = Answer(text, "history")
        elif order_id is None and ORDER_HISTORY.search(question):
            dishes = self.repository.ordered_dishes(user_id)
            text = (
                "Вы уже заказывали:\n" + "\n".join(f"• {dish}" for dish in dishes)
                if dishes else "В истории пока нет оплаченных заказов."
            )
            answer = Answer(text, "history")
        else:
            context = [] if new_chat else self.repository.recent_context(user_id, chat_id)
            orders = self.repository.get_orders(user_id, order_id)
            if order_id is not None and not orders:
                answer = Answer("Заказ не найден среди ваших заказов.", "order")
            else:
                ordered_dishes = self.repository.ordered_dishes(user_id)
                answer = self._answer_from_sources(message, reply_id, context, orders, ordered_dishes)

        self.repository.save_reply(
            reply_id, user_id, chat_id=chat_id, new_chat=new_chat,
            message=message, answer=answer.text, mode=answer.mode, sources=answer.sources,
            phoenix_span_id=current_span_id(),
        )
        duration_ms = round((perf_counter() - started) * 1000)
        logger.info(
            "assistant_reply id=%s mode=%s sources=%d duration_ms=%d",
            reply_id, answer.mode, len(answer.sources), duration_ms,
        )
        return chat_id, reply_id, answer

    def _answer_from_sources(
        self, message: str, reply_id: str, context: list[ConversationTurn], orders: list[OrderDetails],
        ordered_dishes: list[str],
    ) -> Answer:
        contextual_question = None
        if context and FOLLOW_UP.search(message.casefold()):
            previous = context[-1]
            contextual_question = f"{message}\n{previous.message[:400]}\n{previous.answer[:400]}"
        has_order_context = bool(orders or ordered_dishes or ORDER_WORD.search(message.casefold()))
        try:
            with trace_step("assistant.retrieve", "RETRIEVER") as span:
                sources = self.repository.find_sources(message, embed, contextual_question)
                span.set_attribute("assistant.source_count", len(sources))
        except EmbeddingUnavailableError as error:
            self.repository.rollback()
            logger.warning("assistant_error id=%s component=embeddings reason=%s", reply_id, error)
            if not has_order_context:
                return Answer(UNAVAILABLE, "fallback")
            sources = []
        if not sources and not has_order_context:
            return Answer(NO_DATA, "no_data")
        try:
            with trace_step("assistant.openrouter", "LLM") as span:
                span.set_attribute("llm.model_name", self.llm.model)
                answer = self.llm.answer(
                    message, sources, context, orders=orders, ordered_dishes=ordered_dishes,
                )
            return Answer(answer, "rag", sources)
        except OpenRouterError as error:
            logger.warning("assistant_error id=%s component=openrouter reason=%s", reply_id, error)
            return Answer(UNAVAILABLE, "fallback", sources)
