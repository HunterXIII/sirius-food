"""
Ограничение частоты запросов (rate limiting) на Redis.
Счётчик в Redis общий для всех реплик приложения.
"""
from fastapi import HTTPException, Request
from redis import Redis

from app.core.config import settings

redis_client = Redis.from_url(settings.REDIS_URL)


def rate_limit(max_requests: int = 5, window: int = 60):
    """
    Dependency для ограничения частоты запросов.
    Не больше max_requests запросов с одного IP на один путь за window секунд.
    Возбуждает HTTPException 429 при превышении лимита.
    """
    def checker(request: Request):
        # Адреса клиента может не быть (так бывает по стандарту ASGI,
        # например в TestClient). Тогда считаем всех таких клиентов вместе.
        ip = request.client.host if request.client else "unknown"
        key = f"rate_limit:{ip}:{request.url.path}"
        current = redis_client.incr(key)
        # Первый запрос в окне: ключ сам удалится через window секунд.
        if current == 1:
            redis_client.expire(key, window)
        if current > max_requests:
            raise HTTPException(429, "Too many requests")
    return checker
