"""
Точка входа приложения. Выполняет инициализацию FastAPI
и подключение модулей.
Таблицы базы данных создаёт Alembic: alembic upgrade head.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_fastapi_instrumentator import Instrumentator

from app.core.config import settings
from app.core.correlation import CORRELATION_HEADER, correlation_id_middleware
from app.core.logging import setup_logging
from app.core.order_tracing import setup_order_tracing
from app.core.redis import check_redis_connection
from app.core.sentry import setup_sentry
from app.database import SessionLocal
from app.modules.assistant.router import router as assistant_router
from app.modules.assistant.tracing import assistant_tracing
from app.modules.auth.router import router as auth_router
from app.modules.users.router import router as users_router
from app.modules.menu.router import router as menu_router
from app.modules.menu.repository import get_menu_repository
from app.modules.orders.router import router as orders_router
from app.modules.delivery.router import router as delivery_router
from app.modules.payments.router import router as payments_router


def warm_up_menu_cache():
    """Прогрев кеша (cache warm-up): при старте кладём меню в Redis."""
    if not check_redis_connection():
        print("Redis недоступен, прогрев кеша меню пропущен")
        return
    db = SessionLocal()
    try:
        get_menu_repository(db).warm_up_cache()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Код до yield выполняется при старте приложения, после yield - при остановке.
    # Это замена устаревшему @app.on_event("startup").
    setup_logging()
    warm_up_menu_cache()
    with assistant_tracing(settings.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT):
        yield


app = FastAPI(
    title="Sirius.Food API",
    lifespan=lifespan,
    # Swagger раскрывает структуру API, поэтому он есть только при DEBUG=True.
    # openapi.json тоже выключаем: по нему Swagger и строится.
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
)

# CORS: браузер пустит к API только страницы с доменов из ALLOWED_ORIGINS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", CORRELATION_HEADER],
    expose_headers=[CORRELATION_HEADER],
)
app.middleware("http")(correlation_id_middleware)
Instrumentator(excluded_handlers=["/metrics"]).instrument(app).expose(app, include_in_schema=False)

# Пути в auth-роутере уже начинаются с /auth (как в методичке), префикс не нужен.
app.include_router(auth_router, tags=["auth"])

app.include_router(users_router, prefix="/users", tags=["users"])
app.include_router(menu_router, prefix="/menu", tags=["menu"])
app.include_router(orders_router, prefix="/orders", tags=["orders"])
app.include_router(delivery_router, prefix="/delivery", tags=["delivery"])
app.include_router(assistant_router, prefix="/assistant", tags=["assistant"])
app.include_router(payments_router, prefix="/payments", tags=["payments"])

if settings.DEBUG and settings.SENTRY_TEST_ENDPOINT_ENABLED and settings.SENTRY_DSN.get_secret_value():
    @app.post("/_lab9/sentry-test", include_in_schema=False)
    async def sentry_test_error():
        raise RuntimeError("ЛР № 9: контрольная ошибка Sentry")


setup_sentry()
order_provider = setup_order_tracing("api")
if order_provider is not None:
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=order_provider,
        excluded_urls="/metrics",
        exclude_spans=["receive", "send"],
    )
