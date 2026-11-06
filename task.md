# Практическая работа № 7

## Event-driven архитектура: RabbitMQ, Saga и Dead Letter Queue

Дисциплина: Разработка программных модулей и приложений для серверов
Тема: Асинхронное взаимодействие через брокер сообщений, идемпотентность, DLQ
Продолжительность: 2 академических часа (90 минут) + самостоятельная работа
Проект: сквозной пет-проект «Сириус.Еда»
Операционная система: Ubuntu 22.04 LTS или новее

## Цели работы

В ходе выполнения лабораторной работы вы:

- Освоите RabbitMQ как брокер сообщений для асинхронного взаимодействия между компонентами.

- Реализуете публикацию события OrderPaid из сервиса заказов при оплате.

- Напишете consumer'ов для кухни и сервиса доставки, которые реагируют на событие независимо друг от друга.

- Обеспечите идемпотентность consumer'ов, чтобы повторная доставка сообщения не создавала дублей.

- Настроите Dead Letter Queue (DLQ) для «битых» сообщений.

Дополнительно (для 9–10 баллов):

- Реализуете Saga (хореография) — при неудачном назначении курьера деньги возвращаются клиенту, заказ отменяется.

- Реализуете Transactional Outbox — гарантия, что событие не потеряется, даже если RabbitMQ недоступен в момент оплаты.

## Критерии оценивания (10-балльная шкала)


| Баллы | Оценка | Что нужно сделать |
| --- | --- | --- |
| 0–3 | Неудовлетворительно (2) | RabbitMQ не поднят, событие не публикуется, consumer'ы не работают. |
| 4–5 | Удовлетворительно (3) | RabbitMQ работает, событие публикуется, но consumer'ы не подписаны или получают не те сообщения. |
| 6–7 | Хорошо (4) | Событие  OrderPaid  публикуется, кухня и доставка получают его независимо. Проект работает end-to-end. |
| 8 | Отлично (5) | Всё из 6–7 + идемпотентность consumer'ов (повторная доставка не создаёт дублей) + DLQ настроена.  README.md  с архитектурной схемой. Устная защита. |
| 9 | Отлично с плюсом (5+) | Всё из 8 + Saga (хореография): при провале назначения курьера выполняется компенсация (возврат денег, отмена заказа). |
| 10 | Отлично с двойным плюсом (5++) | Всё из 9 + Transactional Outbox (событие не теряется при недоступности брокера), либо интеграционные тесты для consumer'ов, либо защита второго события ( OrderDelivered ). |

## 1. Пререквизиты

Для выполнения работы вам потребуется:

- Ubuntu 22.04 LTS;

- Python 3.11 или новее;

- Docker Engine и Docker Compose;

- Git;

- выполненные лабораторные работы № 2–6 (монолит отрефакторен, внедрены безопасность, кеш, фоновые задачи, gRPC, вынесен delivery в gRPC-сервис).

### Установка дополнительных зависимостей

Нам понадобится библиотека для работы с RabbitMQ из Python:

- aio-pika — асинхронный клиент RabbitMQ. Хорошо ложится на FastAPI.


```bash
source .venv/bin/activate
pip install aio-pika
```

### Запуск инфраструктуры

Добавьте RabbitMQ в docker-compose.yml:


```yaml
services:
  # ... существующие сервисы db, redis ...

  rabbitmq:
    image: rabbitmq:3.13-management
    container_name: sirius_rabbitmq
    ports:
      - "5672:5672"      # AMQP-протокол
      - "15672:15672"    # Веб-интерфейс (Management UI)
    environment:
      RABBITMQ_DEFAULT_USER: sirius
      RABBITMQ_DEFAULT_PASS: sirius
```

Запустите:


```bash
docker compose up -d db redis rabbitmq
```

Проверка: откройте http://localhost:15672 в браузере. Логин: sirius, пароль: sirius. Вы увидите веб-интерфейс RabbitMQ.

## 2. Теоретическое введение

### 2.1. Зачем нужен брокер сообщений

Сейчас при оплате заказа OrderService синхронно вызывает другие сервисы (кухню, доставку). Если один из них упал — заказ не может быть обработан. Если завтра нужно добавить ещё одного потребителя — придётся менять код OrderService.

Event-Driven Architecture решает это: OrderService публикует событие OrderPaid в брокер и забывает. Кухня, доставка и бонусная система сами подписываются на это событие. Они не знают друг о друге, и OrderService не знает о них.

### 2.2. RabbitMQ: Exchange и Queue

В RabbitMQ есть два ключевых понятия:

- Exchange — «сортировочный центр». Publisher отправляет сообщение в Exchange с ключом (routing_key).

- Queue — очередь, в которой хранятся сообщения. Consumer читает из неё.

Exchange связан с очередями через Bindings (правила маршрутизации). По умолчанию используется fanout (всем) или topic (по паттерну ключа).

Для «Сириус.Еды»: используем topic exchange, чтобы разные события (order.paid, order.cancelled) попадали в разные очереди.

### 2.3. Идемпотентность в EDA

RabbitMQ использует гарантию At-Least-Once (доставит как минимум один раз). Это значит, что сообщение может прийти дважды. Если consumer не идемпотентен — при повторной доставке он создаст дубль (например, дважды начислит бонусы).

Решение: хранить event_id в таблице processed_events. Перед обработкой проверять: если event_id уже есть — пропустить.

### 2.4. Dead Letter Queue

Если consumer падает при обработке сообщения (например, невалидный JSON) — сообщение возвращается в очередь и снова падает. Это poison message. Очередь блокируется.

DLQ — отдельная очередь для сообщений, которые не удалось обработать после N попыток. Настраивается через x-dead-letter-exchange при объявлении очереди.

## 3. Пошаговый разбор

### Шаг 1. Настройка подключения к RabbitMQ

Что делаем: создаём инфраструктурный модуль для подключения к RabbitMQ.

Зачем: приложению нужен единый интерфейс для публикации сообщений.

Создайте app/core/rabbitmq.py:


```python
"""
Инфраструктурный модуль для работы с RabbitMQ.
Обеспечивает подключение и публикацию сообщений в exchange.
"""
import aio_pika
from aio_pika import ExchangeType
from app.core.config import settings

# Единый exchange для всех событий проекта.
EXCHANGE_NAME = "sirius_events"


async def get_connection() -> aio_pika.RobustConnection:
    """Создаёт подключение к RabbitMQ. Robust — автоматически переподключается."""
    return await aio_pika.connect_robust(settings.RABBITMQ_URL)


async def publish_event(routing_key: str, payload: dict) -> None:
    """
    Публикует событие в RabbitMQ.
    routing_key — например, 'order.paid'.
    payload — словарь с данными события.
    """
    import json
    connection = await get_connection()
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(
            EXCHANGE_NAME,
            ExchangeType.TOPIC,
            durable=True,  # exchange переживёт перезапуск RabbitMQ
        )
        message = aio_pika.Message(
            body=json.dumps(payload).encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,  # сообщение пишется на диск
        )
        await exchange.publish(message, routing_key=routing_key)
```

Добавьте в app/core/config.py:


```python
class Settings(BaseSettings):
    # ... существующие поля ...
    RABBITMQ_URL: str = "amqp://sirius:sirius@localhost:5672/"
```

Проверка: модуль импортируется без ошибок.

### Шаг 2. Публикация события при оплате заказа

Что делаем: при оплате заказа (или создании) публикуем событие OrderPaid.

Зачем: другие сервисы должны узнать, что заказ оплачен.

В OrderService (там, где обрабатывается оплата заказа) добавьте публикацию события:


```python
from app.core.rabbitmq import publish_event

class OrderService:
    # ... существующий код ...

    async def pay_order(self, order_id: int, current_user: User) -> Order:
        """
        Оплата заказа. После успешной оплаты публикуем событие OrderPaid.
        """
        order = self.repository.get_order(order_id)
        if not order:
            raise OrderNotFoundError()
        if order.customer_id != current_user.id:
            raise AccessDeniedError()

        order.pay()  # меняем статус на 'paid'
        self.repository.save(order)

        # Публикуем событие. Кто его получит — не наша забота.
        await publish_event(
            routing_key="order.paid",
            payload={
                "event_id": str(uuid.uuid4()),  # ключ для идемпотентности
                "order_id": order.id,
                "customer_id": order.customer_id,
                "amount": order.total,
            },
        )

        return order
```

Проверка: после вызова pay_order в RabbitMQ появится сообщение в exchange sirius_events с ключом order.paid.

### Шаг 3. Consumer для кухни

Что делаем: создаём сервис, который слушает событие order.paid и «готовит» заказ.

Зачем: кухня должна узнавать о новых оплаченных заказах.

Создайте app/workers/kitchen_consumer.py (папку app/workers/ создайте, если её нет):


```python
"""
Consumer для кухни. Слушает событие order.paid и регистрирует заказ в очереди кухни.
"""
import asyncio
import json
import aio_pika
from aio_pika import ExchangeType

from app.core.config import settings
from app.database import SessionLocal
from app.models import KitchenOrder, ProcessedEvent

EXCHANGE_NAME = "sirius_events"
QUEUE_NAME = "kitchen_queue"


async def process_message(message: aio_pika.IncomingMessage) -> None:
    """
    Обрабатывает одно сообщение.
    Проверяет идемпотентность, затем создаёт запись для кухни.
    """
    async with message.process():
        payload = json.loads(message.body)
        event_id = payload["event_id"]
        order_id = payload["order_id"]

        db = SessionLocal()
        try:
            # Идемпотентность: если событие уже обработано — пропускаем.
            exists = db.query(ProcessedEvent).filter_by(id=event_id).first()
            if exists:
                return

            # Создаём запись для кухни.
            db.add(KitchenOrder(order_id=order_id, status="pending"))
            db.add(ProcessedEvent(id=event_id))
            db.commit()
            print(f"[Kitchen] Принят заказ {order_id}")
        finally:
            db.close()


async def main() -> None:
    """Запускает consumer и слушает очередь кухни."""
    connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=10)  # не берём больше 10 сообщений одновременно

    exchange = await channel.declare_exchange(
        EXCHANGE_NAME, ExchangeType.TOPIC, durable=True
    )

    # Очередь с настройкой DLQ.
    queue = await channel.declare_queue(
        QUEUE_NAME,
        durable=True,
        arguments={
            "x-dead-letter-exchange": "dlx_exchange",
            "x-dead-letter-routing-key": "kitchen.dlq",
        },
    )

    # Привязываем очередь к exchange с ключом order.paid.
    await queue.bind(exchange, routing_key="order.paid")

    await queue.consume(process_message)
    print("[Kitchen] Ждём события order.paid...")

    await asyncio.Future()  # бесконечное ожидание


if __name__ == "__main__":
    asyncio.run(main())
```

Проверка: запустите python -m app.workers.kitchen_consumer в отдельном терминале. После оплаты заказа в логах появится [Kitchen] Принят заказ 42.

### Шаг 4. Consumer для доставки

Что делаем: создаём consumer для delivery-микросервиса (того, что вынесли в ЛР № 6).

Зачем: отдельный сервис доставки должен независимо реагировать на OrderPaid.

Создайте delivery_worker.py в корне проекта (рядом с delivery_server.py):


```python
"""
Consumer для микросервиса доставки. Слушает событие order.paid
и подготавливает доставку.
"""
import asyncio
import json
import aio_pika
from aio_pika import ExchangeType

EXCHANGE_NAME = "sirius_events"
QUEUE_NAME = "delivery_queue"
RABBITMQ_URL = "amqp://sirius:sirius@localhost:5672/"


async def process_message(message: aio_pika.IncomingMessage) -> None:
    async with message.process():
        payload = json.loads(message.body)
        order_id = payload["order_id"]
        # В реальном проекте — запись в БД доставки.
        print(f"[Delivery] Подготовка доставки для заказа {order_id}")


async def main() -> None:
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=10)

    exchange = await channel.declare_exchange(
        EXCHANGE_NAME, ExchangeType.TOPIC, durable=True
    )

    queue = await channel.declare_queue(QUEUE_NAME, durable=True)
    await queue.bind(exchange, routing_key="order.paid")

    await queue.consume(process_message)
    print("[Delivery] Ждём события order.paid...")

    await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
```

Проверка: запустите python delivery_worker.py в третьем терминале. После оплаты заказа в логах появится [Delivery] Подготовка доставки для заказа 42.

Ключевая мысль: кухня и доставка не знают друг о друге. Они оба получили одно и то же событие, но обрабатывают его по-своему.

### Шаг 5. Настройка Dead Letter Queue

Что делаем: создаём DLQ для сообщений, которые не удалось обработать.

Зачем: «битое» сообщение не должно вечно блокировать очередь.

Создайте app/workers/dlq_setup.py — скрипт, который создаёт DLQ-инфраструктуру. Запустите его один раз:


```python
"""
Скрипт настройки DLQ. Запускается один раз перед стартом consumer'ов.
"""
import asyncio
import aio_pika
from aio_pika import ExchangeType

RABBITMQ_URL = "amqp://sirius:sirius@localhost:5672/"


async def setup() -> None:
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()

    # Создаём DLX exchange.
    dlx = await channel.declare_exchange(
        "dlx_exchange", ExchangeType.DIRECT, durable=True
    )

    # Создаём очередь DLQ.
    dlq = await channel.declare_queue("kitchen_dlq", durable=True)
    await dlq.bind(dlx, routing_key="kitchen.dlq")

    print("DLQ настроена.")
    await connection.close()


if __name__ == "__main__":
    asyncio.run(setup())
```

Проверка: запустите python -m app.workers.dlq_setup. В веб-интерфейсе RabbitMQ (http://localhost:15672) появятся dlx_exchange и kitchen_dlq.

Тест: отправьте в kitchen_queue невалидное сообщение (например, строку not-json через Management UI). Оно не будет обработано, вернётся в очередь, а после исчерпания попыток уйдёт в kitchen_dlq.

### Шаг 6. Запуск и проверка end-to-end

Что делаем: запускаем все процессы и проверяем, что событие доходит до обоих consumer'ов.

- Терминал 1: RabbitMQ (уже запущен через docker compose).

- Терминал 2: монолит — uvicorn app.main:app --reload.

- Терминал 3: кухня — python -m app.workers.kitchen_consumer.

- Терминал 4: доставка — python delivery_worker.py.

- Swagger: выполните POST /orders/{id}/pay.

Ожидаемый результат:

- В терминале кухни: [Kitchen] Принят заказ 42.

- В терминале доставки: [Delivery] Подготовка доставки для заказа 42.

- В веб-интерфейсе RabbitMQ видно exchange sirius_events, очереди kitchen_queue и delivery_queue.

### Шаг 7. Проверка идемпотентности

Что делаем: убеждаемся, что повторная доставка не создаёт дубль.

- Отправьте то же событие OrderPaid вручную через веб-интерфейс RabbitMQ (с тем же event_id).

- В логах кухни не должно появиться повторной записи [Kitchen] Принят заказ 42.

- В БД не должно быть двух KitchenOrder для одного order_id.

Ожидаемый результат: идемпотентность работает.

## 4. Задание для самостоятельной работы (9–10 баллов)

Вам необходимо доработать систему, выбрав одно из заданий:

Вариант А (9 баллов). Saga (хореография) для компенсации.

Реализуйте сценарий: при создании доставки, если курьер не найден, публикуется событие DeliveryFailed. PaymentService (или OrderService) слушает это событие и выполняет компенсацию:

- Меняет статус заказа на cancelled.

- Возвращает деньги клиенту (эмуляция — запись в лог и обновление баланса).

- Публикует событие OrderCancelled.

Каждая компенсация должна быть идемпотентной (через event_id или уникальный compensation_key).

Вариант Б (10 баллов). Transactional Outbox.

Проблема: если RabbitMQ недоступен в момент оплаты, событие OrderPaid не будет опубликовано — заказ оплачен, но кухня о нём не узнает.

Решение:

- Создайте таблицу outbox в БД.

- В OrderService.pay_order записывайте событие в outbox в одной транзакции с обновлением статуса заказа.

- Отдельный фоновый воркер читает из outbox и публикует события в RabbitMQ. После успешной публикации — помечает запись как published.

Это гарантирует, что событие никогда не потеряется, даже если RabbitMQ упал.

Вариант В (10 баллов). Интеграционные тесты для consumer'ов.

Напишите тесты (pytest + testcontainers или pytest-rabbitmq), которые проверяют:

- Consumer обрабатывает корректное сообщение.

- Consumer идемпотентен (повторная обработка не создаёт дубль).

- «Битое» сообщение не ломает очередь (уходит в DLQ).

Задание сдаётся в виде:

- работающей системы (демонстрация);

- README.md с архитектурной схемой (publisher → exchange → queues → consumers);

- устной защиты.

## 5. Контрольные вопросы для защиты работы

- Зачем публиковать событие OrderPaid, а не вызывать кухню и доставку напрямую по gRPC?

- Что такое Exchange и Queue в RabbitMQ? Чем они отличаются?

- Что такое идемпотентность? Как вы её обеспечили в этой работе?

- Почему RabbitMQ использует At-Least-Once, а не Exactly-Once?

- Что такое Dead Letter Queue и зачем она нужна?

- Что произойдёт, если consumer упадёт в момент обработки сообщения?

- Чем событие отличается от команды? Приведите пример для «Сириус.Еды».

- Как Saga решает проблему распределённых транзакций?

## 6. Приложение: структура проекта после внедрения


```text
sirius_food/
├── app/
│   ├── core/
│   │   ├── config.py          # + RABBITMQ_URL
│   │   └── rabbitmq.py        # publish_event
│   ├── modules/
│   │   └── orders/
│   │       └── service.py     # + publish_event в pay_order
│   └── workers/
│       ├── kitchen_consumer.py
│       └── dlq_setup.py
├── delivery_worker.py          # consumer для микросервиса доставки
├── delivery_server.py          # gRPC-сервер (из ЛР № 6)
├── docker-compose.yml          # + rabbitmq
└── requirements.txt            # + aio-pika

```
