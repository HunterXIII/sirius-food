"""Чат поддержки, история и оценка полезности ответа."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from opentelemetry.trace import StatusCode
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.database import get_db
from app.exceptions import NotFoundError
from app.modules.assistant.openrouter import OpenRouterClient
from app.modules.assistant.repository import AssistantRepository, Source
from app.modules.assistant.service import AssistantService
from app.modules.assistant.tracing import send_feedback, trace_step

router = APIRouter()


class ChatRequest(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    chat_id: UUID | None = None
    order_id: Annotated[int | None, Field(gt=0, le=2147483647)] = None


class ChatResponse(BaseModel):
    chat_id: UUID
    reply_id: UUID
    answer: str
    mode: Literal["rag", "order", "history", "no_data", "fallback"]
    sources: list[Source]


class ChatHistoryItem(ChatResponse):
    message: str
    created_at: datetime
    helpful: bool | None


class ChatHistoryResponse(BaseModel):
    items: list[ChatHistoryItem]
    next_before: UUID | None


class FeedbackRequest(BaseModel):
    helpful: bool


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, user=Depends(get_current_user), db: Session = Depends(get_db)):
    service = AssistantService(
        AssistantRepository(db),
        OpenRouterClient(settings.OPENROUTER_API_KEY, settings.OPENROUTER_MODEL),
    )
    try:
        with trace_step("assistant.chat", "CHAIN") as span:
            span.set_attribute("input.value", payload.message)
            chat_id, reply_id, answer = service.chat(
                payload.message, user.id, payload.order_id, str(payload.chat_id) if payload.chat_id else None,
            )
            span.set_attribute("output.value", answer.text)
            span.set_attribute("assistant.mode", answer.mode)
            span.set_attribute("assistant.source_count", len(answer.sources))
            if answer.mode == "fallback":
                span.set_status(StatusCode.ERROR)
    except NotFoundError as error:
        raise HTTPException(404, str(error)) from error
    return ChatResponse(
        chat_id=chat_id, reply_id=reply_id, answer=answer.text, mode=answer.mode, sources=answer.sources,
    )


@router.get("/history", response_model=ChatHistoryResponse)
def chat_history(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    before: UUID | None = None,
    chat_id: UUID | None = None,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    repository = AssistantRepository(db)
    chat_key = str(chat_id) if chat_id else None
    if chat_key is not None and not repository.owns_chat(user.id, chat_key):
        raise HTTPException(404, "Чат не найден")
    replies = repository.get_history(user.id, limit + 1, str(before) if before else None, chat_key)
    if replies is None:
        raise HTTPException(404, "Сообщение не найдено")
    next_before = replies[limit - 1].id if len(replies) > limit else None
    return ChatHistoryResponse(
        items=[
            ChatHistoryItem(
                chat_id=reply.chat_id,
                reply_id=reply.id,
                message=reply.message,
                answer=reply.answer,
                mode=reply.mode,
                sources=reply.sources,
                helpful=reply.helpful,
                created_at=reply.created_at,
            )
            for reply in replies[:limit]
        ],
        next_before=next_before,
    )


@router.post("/replies/{reply_id}/feedback", status_code=204)
def rate_reply(
    reply_id: UUID, payload: FeedbackRequest, user=Depends(get_current_user), db: Session = Depends(get_db),
):
    reply = AssistantRepository(db).rate_reply(str(reply_id), user.id, payload.helpful)
    if reply is None:
        raise HTTPException(404, "Ответ не найден")
    if reply.phoenix_span_id:
        send_feedback(settings.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT, reply.phoenix_span_id, payload.helpful)
    return Response(status_code=204)
