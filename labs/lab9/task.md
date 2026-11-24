# Практическая работа № 9

## Observability: логи, метрики и трассировка в «Сириус.Еде»

Дисциплина: Разработка программных модулей и приложений для серверов
Тема: Наблюдаемость распределённой системы: correlation ID, структурированные логи, метрики Prometheus и Grafana, трассировка
Продолжительность: 2 практических семинара + самостоятельная работа
Проект: сквозной пет-проект «Сириус.Еда»
Стек: Python 3.11+, FastAPI, RabbitMQ, Redis, Prometheus, Grafana, structlog, OpenTelemetry (для 10 баллов)
Операционная система: Ubuntu 22.04 LTS или новее (допускаются Windows и macOS)

## Цели работы

В ходе выполнения лабораторной работы вы:

1. Освоите понятие observability и три её столпа: логи, метрики, трассировка.

1. Реализуете сквозной correlation_id, который проходит через монолит, RabbitMQ и consumer кухни.

1. Настроите структурированные JSON-логи в stdout.

1. Подключите метрики Prometheus к монолиту и RabbitMQ.

1. Развернёте Grafana и построите дашборд с ключевыми метриками.

1. Проведёте расследование: по correlation_id найдёте весь путь заказа и метрики за этот период.

Дополнительно (для 9–10 баллов, на выбор):

1. Подключите Sentry и увидите ошибку с контекстом (9 баллов).

1. Подключите OpenTelemetry и увидите распределённый трейс заказа (10 баллов).

## Критерии оценивания (10-балльная шкала)

| Баллы | Что нужно сделать |
| --- | --- |
| 0–3 | Correlation ID не добавлен, логи не структурированы, метрик нет. |
| 4–5 | Correlation ID есть в монолите, но не передаётся в RabbitMQ. Логи частично структурированы. |
| 6–7 | Correlation ID проходит через все сервисы, JSON-логи в stdout, Prometheus собирает метрики. |
| 8 | Всё из 6–7 + дашборд Grafana + расследование заказа по correlation_id в логах. |
| 9 | Всё из 8 + Sentry с ошибкой и correlation_id. |
| 10 | Всё из 9 + OpenTelemetry и распределённый трейс заказа в Jaeger. |

Критерий успеха уровня 8: вы можете отправить заказ с X-Correlation-ID, найти этот ID в логах монолита и кухни, показать метрики за этот период в Grafana.

## 1. Пререквизиты

Для выполнения работы требуется:

- Запущенный проект «Сириус.Еда» после ЛР № 7 (монолит, gRPC-сервис доставки, RabbitMQ, Redis, consumer кухни);

- Docker и Docker Compose;

- Python 3.11+ и виртуальное окружение проекта;

- VS Code и терминал;

- Базовые навыки работы с curl и docker logs.

### 1.1. Проверка окружения

Что делаем: убеждаемся, что монолит и RabbitMQ работают.

Зачем: без работающего проекта мы не сможем проверить correlation ID и метрики.

```bash
cd "/home/sirius/projects/sirius_food"
docker compose up -d db redis rabbitmq
source .venv/bin/activate
uvicorn app.main:app --reload
```

Во втором терминале:

```bash
curl -s http://127.0.0.1:8000/menu/items
```

Ожидаемый ответ: JSON с массивом блюд.

### 1.2. Проверка consumer'а кухни

Что делаем: убеждаемся, что consumer кухни запущен и слушает очередь.

Зачем: correlation ID должен пройти через RabbitMQ до кухни. Если consumer не запущен, мы не увидим второй конец цепочки.

```bash
# В отдельном терминале.
python -m app.workers.kitchen_consumer
```

Ожидаемый вывод: сообщение о том, что consumer ждёт события.

## 2. Теоретическое введение

### 2.1. Что такое observability

Observability (наблюдаемость) — способность системы отвечать на вопрос «что происходит внутри?» по её внешним проявлениям: логам, метрикам, трассировкам.

Чем отличается от мониторинга: мониторинг отвечает на заранее заданные вопросы («сервер жив?»). Observability позволяет отвечать на новые вопросы, которые вы не предвидели («почему заказы 42–44 потерялись, а 45 прошёл?»).

### 2.2. Три столпа observability

| Столп | Отвечает на вопрос | Пример в «Сириус.Еде» |
| --- | --- | --- |
| Логи | Что произошло? | «Заказ 42 создан» |
| Метрики | Как система себя чувствует? | RPS, latency, ошибки 5xx |
| Трассировка | Где прошёл запрос? | Заказ 42: монолит → RabbitMQ → кухня |

Правило: по одному correlation_id можно связать все три источника.

### 2.3. Correlation ID и trace ID: не путать

| Критерий | correlation_id | trace_id |
| --- | --- | --- |
| Кто генерирует | Ваше приложение (middleware) | OTel SDK (автоматически) |
| Назначение | Связать бизнес-операцию | Связать технические вызовы |
| Где живёт | Логи, БД, заголовки, тикеты поддержки | Jaeger, Tempo |
| Сколько живёт | Всю бизнес-операцию | Один технический вызов |

Пример: один заказ может включать несколько HTTP-запросов (создание, оплата, отмена). У каждого свой trace_id, но у всех один correlation_id.

### 2.4. Логи: stdout и JSON

stdout — стандартный поток вывода. В Docker приложение пишет логи в stdout, а Docker сам их собирает. Поэтому docker logs sirius_app показывает логи без настройки.

Почему не файл: файл внутри контейнера исчезнет при пересоздании и не виден снаружи без docker exec. При нескольких репликах — несколько файлов на разных машинах.

JSON-логи позволяют фильтровать и агрегировать записи программно. Текстовый лог можно прочитать глазами, но нельзя отфильтровать «все логи с order_id=42».

Пример хорошего лога:

```json
{
  "timestamp": "2026-11-12T12:00:01Z",
  "level": "INFO",
  "message": "order_created",
  "service": "order-service",
  "order_id": 42,
  "user_id": 7,
  "correlation_id": "a1b2c3d4",
  "duration_ms": 15
}
```

### 2.5. Метрики: RED и USE

RED — три метрики для каждого эндпоинта:

- Rate — сколько запросов в секунду;

- Errors — сколько ошибок;

- Duration — сколько длится запрос.

USE — три метрики для ресурсов:

- Utilization — процент использования (CPU, память);

- Saturation — насколько ресурс перегружен (длина очереди);

- Errors — ошибки ресурса.

Для «Сириус.Еды» важны:

| Метрика | Тип | Зачем |
| --- | --- | --- |
| RPS на /orders/create | Counter | Сколько заказов в секунду |
| Latency p95 на /menu/items | Histogram | Не тормозит ли меню |
| Ошибки 5xx | Counter | Не падает ли API |
| Длина очереди RabbitMQ | Gauge | Не копится ли очередь кухни |
| Cache hit rate Redis | Gauge | Работает ли кеш |

### 2.6. Prometheus и Grafana

Prometheus — система мониторинга. Периодически собирает метрики с приложения по адресу /metrics и хранит их.

Grafana — визуализация. Читает данные из Prometheus и строит графики и дашборды.

Схема:

### 2.7. Трассировка: span и trace

Trace — весь путь запроса через все сервисы.

Span — один шаг в этом пути: имя, время начала и конца, родитель, атрибуты.

Пример трейса заказа 42:

```text
Trace: заказ 42
├── Span 1: HTTP POST /orders          [15 ms]
│   └── Span 2: OrderService.create    [10 ms]
│       ├── Span 3: DB.insert          [2 ms]
│       └── Span 4: RabbitMQ.publish   [1 ms]
└── Span 5: Kitchen.consume            [5 ms]
```

### 2.8. Context propagation

Context propagation — передача trace_id и span_id между сервисами через стандартный заголовок traceparent. OTel SDK делает это автоматически для HTTP, gRPC и RabbitMQ.

Заголовок не накапливает информацию. Он содержит только trace_id и span_id родителя. Сами данные о span'ах каждый сервис отдельно отправляет в Jaeger.

## 3. Что уже есть в проекте

К этому моменту у вас есть:

- монолит FastAPI с REST API;

- consumer кухни на RabbitMQ;

- Redis для кеша;

- Docker Compose с сервисами.

Чего нет:

- correlation ID в монолите и consumer'ах;

- структурированных логов;

- Prometheus и Grafana;

- Sentry и OpenTelemetry (для 9–10 баллов).

## 4. Пошаговый разбор

### 4.1. Correlation ID в монолите

Что делаем: добавляем middleware, которая генерирует или подхватывает X-Correlation-ID.

Зачем: без единого ID нельзя связать логи монолита и кухни. Это фундамент для всех следующих этапов.

Создайте app/core/correlation.py:

```python
"""
Middleware для correlation_id.
Генерирует ID, если клиент не передал его, и кладёт в request.state.
"""
import uuid
from fastapi import Request


async def correlation_id_middleware(request: Request, call_next):
    # Берём ID из заголовка или генерируем новый.
    correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())

    # Кладём в request.state, чтобы был доступен в эндпоинтах.
    request.state.correlation_id = correlation_id

    # Передаём запрос дальше в эндпоинт.
    response = await call_next(request)

    # Возвращаем ID клиенту.
    response.headers["X-Correlation-ID"] = correlation_id
    return response
```

Подключите middleware в app/main.py:

```python
from app.core.correlation import correlation_id_middleware

app.middleware("http")(correlation_id_middleware)
```

Проверка:

```bash
curl -v -X POST http://127.0.0.1:8000/orders/create \
  -H "Content-Type: application/json" \
  -H "X-Correlation-ID: demo-42" \
  -d '{"item_id": 1, "quantity": 1}'
```

В ответе должен быть заголовок X-Correlation-ID: demo-42.

### 4.2. Структурированные логи

Что делаем: настраиваем structlog для JSON-логов в stdout.

Зачем: текстовые логи нельзя фильтровать. JSON-логи — можно.

Установите зависимость:

```bash
pip install structlog
```

Создайте app/core/logging.py:

```python
"""
Настройка structlog для JSON-логов в stdout.
"""
import logging
import sys
import structlog


def setup_logging():
    # Базовый logging пишет в stdout.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )

    # structlog добавляет JSON-рендеринг.
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
    )
```

Вызовите setup_logging() при старте приложения в app/main.py.

Используйте логгер в эндпоинте:

```python
import structlog
from fastapi import Request

logger = structlog.get_logger()


@app.post("/orders/create")
async def create_order(payload: OrderCreate, request: Request):
    correlation_id = request.state.correlation_id

    logger.info(
        "order_created",
        order_id=42,
        user_id=payload.user_id,
        correlation_id=correlation_id,
        duration_ms=15,
    )

    return {"status": "success", "order_id": 42}
```

Проверка:

```bash
docker logs sirius_app | jq 'select(.correlation_id == "demo-42")'
```

### 4.3. Передача correlation_id через RabbitMQ

Что делаем: при публикации события кладём X-Correlation-ID в заголовки сообщения, а consumer читает его.

Зачем: без этого ID теряется при переходе через брокер. Кухня не знает, к какому запросу относится событие.

При публикации:

```python
import aio_pika
import json

message = aio_pika.Message(
    body=json.dumps(payload).encode(),
    headers={"X-Correlation-ID": correlation_id},
)
await exchange.publish(message, routing_key="order.paid")
```

При обработке:

```python
async def process_message(message: aio_pika.IncomingMessage):
    correlation_id = message.headers.get("X-Correlation-ID", "unknown")

    logger.info(
        "order_received",
        order_id=order_id,
        correlation_id=correlation_id,
    )
```

Проверка: в логах кухни должен быть тот же correlation_id, что в логах монолита.

### 4.4. Метрики Prometheus

Что делаем: подключаем prometheus-fastapi-instrumentator и разворачиваем Prometheus.

Зачем: метрики показывают тренды: RPS, latency, ошибки. Без них мы видим только отдельные события в логах.

Установите зависимость:

```bash
pip install prometheus-fastapi-instrumentator
```

В app/main.py:

```python
from prometheus_fastapi_instrumentator import Instrumentator

# Автоматически добавляет /metrics с RED-метриками.
Instrumentator().instrument(app).expose(app)
```

Проверка:

```bash
curl -s http://127.0.0.1:8000/metrics | grep http_requests_total
```

Добавьте в docker-compose.yml Prometheus:

```yaml
prometheus:
  image: prom/prometheus:latest
  container_name: sirius_prometheus
  ports:
    - "9090:9090"
  volumes:
    - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml
```

Создайте prometheus/prometheus.yml:

```yaml
global:
  scrape_interval: 5s

scrape_configs:
  - job_name: "sirius_app"
    static_configs:
      - targets: ["host.docker.internal:8000"]
```

Запустите:

```bash
docker compose up -d prometheus
```

Проверка: откройте http://localhost:9090/targets — таргет sirius_app должен быть UP.

### 4.5. Grafana и дашборд

Что делаем: разворачиваем Grafana, подключаем Prometheus и строим дашборд.

Зачем: Prometheus хранит метрики, но не рисует. Grafana — «приборная панель» системы.

Добавьте в docker-compose.yml:

```yaml
grafana:
  image: grafana/grafana:latest
  container_name: sirius_grafana
  ports:
    - "3000:3000"
  environment:
    - GF_SECURITY_ADMIN_PASSWORD=admin
```

Запустите:

```bash
docker compose up -d grafana
```

Откройте http://localhost:3000, войдите (admin / admin), добавьте Prometheus как datasource (http://prometheus:9090).

Создайте дашборд с панелями:

| Панель | Запрос PromQL |
| --- | --- |
| RPS | rate(http_requests_total[1m]) |
| Latency p95 | histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[1m])) |
| Ошибки 5xx | rate(http_requests_total{status=~"5.."}[1m]) |
| Длина очереди RabbitMQ | rabbitmq_queue_messages{queue="kitchen_queue"} |
| Cache hit rate Redis | rate(redis_keyspace_hits_total[5m]) / (rate(redis_keyspace_hits_total[5m]) + rate(redis_keyspace_misses_total[5m])) |

Проверка: панели показывают данные после нескольких запросов к API.

### 4.6. Расследование заказа

Что делаем: отправляем заказ с correlation_id = demo-42, находим его во всех источниках.

Зачем: это критерий сдачи. Вы должны уметь провести расследование, а не просто настроить инструменты.

1. Отправьте заказ:

```bash
curl -X POST http://127.0.0.1:8000/orders/create \
  -H "Content-Type: application/json" \
  -H "X-Correlation-ID: demo-42" \
  -d '{"item_id": 1, "quantity": 1}'
```

1. Найдите логи монолита:

```bash
docker logs sirius_app | jq 'select(.correlation_id == "demo-42")'
```

1. Найдите логи кухни:

```bash
docker logs sirius_kitchen | jq 'select(.correlation_id == "demo-42")'
```

1. Откройте Grafana и посмотрите метрики за этот период.

Критерий: в логах обоих сервисов есть correlation_id = demo-42, а в Grafana видно всплеск RPS и latency.

## 5. Задания для самостоятельной работы (9–10 баллов)

### На 9 баллов. Sentry

Зачем это нужно. Логи показывают всё, Sentry — только ошибки, но с контекстом: стектрейс, URL, correlation_id, user_id. Это «пожарная сигнализация» для ошибок.

Что сделать:

1. Зарегистрироваться в Sentry (бесплатный тариф).

1. Установить sentry-sdk[fastapi].

1. Подключить Sentry в app/main.py с DSN из .env.

1. Вызвать ошибку 500 (например, GET /orders/999999 без обработки).

1. Открыть Sentry: увидеть ошибку, стектрейс, correlation_id.

Критерий: в Sentry видна ошибка с correlation_id.

### На 10 баллов. OpenTelemetry и Jaeger

Зачем это нужно. Трейс показывает весь путь запроса: HTTP → OrderService → RabbitMQ → Kitchen. Видно, какой span самый долгий.

Что сделать:

1. Установить opentelemetry-sdk, opentelemetry-instrumentation-fastapi, opentelemetry-exporter-otlp.

1. Подключить OTel к монолиту и consumer'у кухни.

1. Развернуть Jaeger в Docker Compose.

1. Отправить заказ с correlation_id = demo-42.

1. Открыть Jaeger: найти трейс заказа, увидеть все span'ы, найти самый долгий.

Критерий: в Jaeger виден трейс заказа 42, все span'ы в одном трейсе.

## 6. Чек-лист перед сдачей

| № | Проверка | Что должно быть |
| --- | --- | --- |
| 1 | curl -v с X-Correlation-ID | Заголовок есть в ответе |
| 2 | docker logs sirius_app \| jq | JSON с correlation_id |
| 3 | docker logs sirius_kitchen \| jq | Тот же correlation_id |
| 4 | http://localhost:9090/targets | Таргет sirius_app — UP |
| 5 | Grafana дашборд | Панели RPS, latency, ошибки работают |
| 6 | Расследование | Логи и метрики по demo-42 найдены |
| 7 | Sentry (9 баллов) | Ошибка с correlation_id |
| 8 | Jaeger (10 баллов) | Трейс заказа 42 |

## 7. Контрольные вопросы

1. Чем observability отличается от мониторинга?

1. Зачем нужен correlation_id? Что будет, если его нет?

1. Почему логи пишем в stdout, а не в файл?

1. Чем correlation_id отличается от trace_id?

1. Что такое RED-метрики?

1. Что такое span и trace?

1. Что такое context propagation?

1. Чем Sentry отличается от логов?

1. Что такое кардинальность метрик и почему она опасна?

1. Зачем нужен request.state и call_next в middleware?

## 8. Что сдавать

Работа сдаётся очно на ноутбуке студента. На защите вы:

1. Запускаете проект и Grafana.

1. Показываете curl с X-Correlation-ID и логи двух сервисов.

1. Показываете дашборд Grafana с метриками.

1. Проводите расследование заказа demo-42.

1. Для 9–10 баллов показываете Sentry и Jaeger.

1. Отвечаете на контрольные вопросы.

Состав сдачи: работающее приложение + README.md + устная защита.

## Приложение А. Команды для проверки

```bash
# Отправить заказ с correlation_id.
curl -X POST http://127.0.0.1:8000/orders/create \
  -H "Content-Type: application/json" \
  -H "X-Correlation-ID: demo-42" \
  -d '{"item_id": 1, "quantity": 1}'

# Логи монолита.
docker logs sirius_app | jq 'select(.correlation_id == "demo-42")'

# Логи кухни.
docker logs sirius_kitchen | jq 'select(.correlation_id == "demo-42")'

# Метрики.
curl -s http://127.0.0.1:8000/metrics | grep http_requests_total
```

## Приложение Б. Частые ошибки

| Симптом | Причина | Решение |
| --- | --- | --- |
| correlation_id = None | Middleware не подключена | Подключить в app/main.py |
| Логи не в JSON | structlog не настроен | Вызвать setup_logging() при старте |
| /metrics не отвечает | Instrumentator не подключён | Добавить Instrumentator().instrument(app).expose(app) |
| Prometheus не видит таргет | Неверный адрес в prometheus.yml | Использовать host.docker.internal:8000 |
| Grafana не показывает данные | Datasource не подключён | Добавить Prometheus как datasource |
| correlation_id не дошёл до кухни | Не передан в заголовках RabbitMQ | Добавить в aio_pika.Message(headers=...) |
