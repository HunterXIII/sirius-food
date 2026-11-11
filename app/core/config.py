"""
Настройки приложения. Читаются из файла .env (или переменных окружения).
Секретов в коде нет.
"""
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
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "openrouter/free"
    EMBEDDING_MODEL_DIR: str = "/opt/embeddings"
    DEBUG: bool = False
    ALLOWED_ORIGINS: list[str] = []
    # Какую реализацию репозиториев использовать (из lab2):
    # "postgres" или "memory" (данные в оперативной памяти).
    REPOSITORY: str = "postgres"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
