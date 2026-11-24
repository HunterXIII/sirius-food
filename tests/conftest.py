import os


# Тесты можно запускать на чистом checkout без рабочего .env.
os.environ.setdefault("SECRET_KEY", "sirius-test-signing-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379")
os.environ.setdefault("SENTRY_DSN", "")
os.environ.setdefault("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "")
os.environ.setdefault("ORDER_OTLP_TRACES_ENDPOINT", "")
