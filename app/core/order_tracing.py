"""Трейсы заказов в Jaeger и передача W3C trace context через outbox."""

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from app.core.config import settings

propagator = TraceContextTextMapPropagator()
order_tracer = trace.get_tracer(__name__)


def setup_order_tracing(service: str) -> TracerProvider | None:
    if not settings.ORDER_OTLP_TRACES_ENDPOINT:
        return None
    provider = TracerProvider(resource=Resource.create({"service.name": f"sirius-{service}"}))
    exporter = OTLPSpanExporter(endpoint=settings.ORDER_OTLP_TRACES_ENDPOINT, timeout=3)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return provider


def current_traceparent() -> str | None:
    headers: dict[str, str] = {}
    propagator.inject(headers)
    return headers.get("traceparent")


def extract_parent(value):
    return propagator.extract({"traceparent": value} if isinstance(value, str) else {})
