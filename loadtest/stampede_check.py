"""
Проверка cache stampede.
Удаляет ключ menu:all (как будто истёк TTL) и в один момент шлёт 200
запросов GET /menu/items. Печатает, сколько раз за это время PostgreSQL
читал таблицу menu_items.
Наш запрос к меню выполняется за миллисекунды, и промахи почти не
пересекаются. Поэтому имитируем медленную БД под нагрузкой: на 2 секунды
блокируем таблицу menu_items, и все запросы к ней ждут.
Запуск из корня проекта (сервер должен работать):
    python -m loadtest.stampede_check
"""
import threading
import time

import httpx
from sqlalchemy import create_engine, text

from app.core.config import settings
from app.core.redis import redis_client

URL = "http://127.0.0.1:8000/menu/items"
REQUESTS = 200

engine = create_engine(settings.DATABASE_URL)


def menu_items_reads() -> int:
    """Сколько раз PostgreSQL читал таблицу menu_items с момента запуска."""
    # Статистику PostgreSQL обновляет с задержкой (до 10 секунд), поэтому ждём.
    time.sleep(11)
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT seq_scan + coalesce(idx_scan, 0) "
            "FROM pg_stat_user_tables WHERE relname = 'menu_items'"
        )).scalar()


# Соединения открываем заранее, чтобы все запросы ушли одновременно.
clients = [httpx.Client(timeout=30) for _ in range(REQUESTS)]
for client in clients:
    client.get(URL)

codes = []
barrier = threading.Barrier(REQUESTS)


def worker(client):
    barrier.wait()  # все потоки стартуют в один момент
    codes.append(client.get(URL).status_code)


before = menu_items_reads()
with engine.connect() as conn:
    # Пока транзакция открыта, SELECT из menu_items ждёт.
    conn.execute(text("LOCK TABLE menu_items IN ACCESS EXCLUSIVE MODE"))
    redis_client.delete("menu:all")
    threads = [threading.Thread(target=worker, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    time.sleep(2)
    conn.rollback()  # снимаем блокировку
for t in threads:
    t.join()
after = menu_items_reads()

print(f"Запросов: {REQUESTS}, ответов 200: {codes.count(200)}")
print(f"Чтений menu_items в PostgreSQL: {after - before}")
