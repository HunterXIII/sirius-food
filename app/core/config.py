"""
Настройки приложения. Читаются из файла .env (или переменных окружения).
Секретов в коде нет.
"""
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения, загружаемые из .env."""
    # Без SECRET_KEY и DATABASE_URL приложение не запустится (Secure by Default).
    SECRET_KEY: str
    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379"
    RABBITMQ_URL: str = "amqp://sirius:sirius@localhost:5672/"
    DELIVERY_GRPC_TARGET: str = "127.0.0.1:50051"
    DELIVERY_GRPC_BIND: str = "127.0.0.1:50051"
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT: str = ""
    YOOKASSA_SHOP_ID: str = ""
    YOOKASSA_SECRET_KEY: SecretStr = SecretStr("")
    YOOKASSA_RETURN_URL: str = "http://127.0.0.1:8000/docs"
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "openrouter/free"
    ASSISTANT_MAX_DOCUMENTS: int = Field(default=6, ge=1)
    ASSISTANT_MAX_COSINE_DISTANCE: float = Field(default=0.20, ge=0, le=2)
    EMBEDDING_MODEL_DIR: str = "/opt/embeddings"
    DEBUG: bool = False
    ALLOWED_ORIGINS: list[str] = []
    # Какую реализацию репозиториев использовать (из lab2):
    # "postgres" или "memory" (данные в оперативной памяти).
    REPOSITORY: str = "postgres"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
