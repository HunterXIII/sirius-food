from re import compile
from uuid import uuid4

from fastapi import Request
from opentelemetry import trace
import sentry_sdk

from app.core.config import settings

CORRELATION_HEADER = "X-Correlation-ID"
VALID_ID = compile(r"[A-Za-z0-9_.:-]{1,128}")


async def correlation_id_middleware(request: Request, call_next):
    supplied = request.headers.get(CORRELATION_HEADER, "")
    correlation_id = supplied if VALID_ID.fullmatch(supplied) else str(uuid4())
    request.state.correlation_id = correlation_id
    trace.get_current_span().set_attribute("correlation_id", correlation_id)
    if settings.SENTRY_DSN.get_secret_value():
        sentry_sdk.set_tag("correlation_id", correlation_id)

    response = await call_next(request)
    response.headers[CORRELATION_HEADER] = correlation_id
    return response
