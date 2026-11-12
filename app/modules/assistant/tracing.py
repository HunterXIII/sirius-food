"""Отправка технических трейсов ассистента в Phoenix."""

import logging
from contextlib import contextmanager
from time import sleep
from typing import TYPE_CHECKING

import httpx
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

if TYPE_CHECKING:
    from app.modules.assistant.repository import Source

tracer = trace.NoOpTracer()
provider = None
logger = logging.getLogger("uvicorn.error.assistant")


@contextmanager
def assistant_tracing(endpoint: str):
    global tracer, provider
    if not endpoint:
        yield
        return

    provider = TracerProvider(resource=Resource.create({
        "service.name": "sirius-food-api",
        "openinference.project.name": "sirius-food",
    }))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, timeout=3)))
    tracer = provider.get_tracer(__name__)
    try:
        yield
    finally:
        tracer = trace.NoOpTracer()
        provider.shutdown()
        provider = None


@contextmanager
def trace_step(name: str, kind: str):
    with tracer.start_as_current_span(
        name,
        attributes={"openinference.span.kind": kind},
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except Exception as error:
            # Сообщения исключений могут содержать данные запроса или провайдера.
            span.set_status(trace.StatusCode.ERROR)
            span.set_attribute("error.type", type(error).__name__)
            raise


def record_retrieval(sources: list["Source"], distances: list[float] | None = None):
    span = trace.get_current_span()
    if not span.is_recording():
        return
    span.set_attribute("assistant.retrieval_method", "exact" if distances is None else "vector")
    for index, source in enumerate(sources):
        prefix = f"retrieval.documents.{index}.document"
        span.set_attribute(f"{prefix}.id", source.key)
        span.set_attribute(f"{prefix}.content", f"{source.title}\n{source.facts}")
        if distances is not None:
            span.set_attribute(f"{prefix}.score", 1.0 - distances[index])


def current_span_id() -> str | None:
    span = trace.get_current_span()
    return f"{span.get_span_context().span_id:016x}" if span.is_recording() else None


def send_feedback(endpoint: str, span_id: str, helpful: bool):
    endpoint = endpoint.rstrip("/")
    if not endpoint.endswith("/v1/traces"):
        return

    # Оценка может прийти раньше, чем пакетный экспорт отправит сам спан.
    if provider is not None:
        provider.force_flush(timeout_millis=2000)

    url = endpoint.removesuffix("/v1/traces") + "/v1/span_annotations"
    annotation = {
        "span_id": span_id,
        "name": "helpfulness",
        "identifier": "assistant-feedback",
        "annotator_kind": "HUMAN",
        "result": {"label": "helpful" if helpful else "not_helpful", "score": int(helpful)},
    }
    try:
        for attempt in range(3):
            response = httpx.post(url, params={"sync": "true"}, json={"data": [annotation]}, timeout=2)
            if response.status_code != 404 or attempt == 2:
                response.raise_for_status()
                if not response.json().get("data"):
                    logger.warning("Phoenix не подтвердил сохранение оценки")
                return
            sleep(0.2)
    except (httpx.HTTPError, ValueError):
        logger.warning("Не удалось отправить оценку в Phoenix", exc_info=False)
