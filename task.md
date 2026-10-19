# Лабораторная работа № 5

## Асинхронность и фоновые задачи: внедрение Celery

Дисциплина: Разработка программных модулей и приложений для серверов  
Тема: Асинхронность и фоновые задачи в production: Celery, идемпотентность, ретраи, Dead Letter Queue  
Продолжительность: 2 академических часа (90 минут) + самостоятельная работа  
Проект: сквозной пет-проект «Сириус.Еда»  
Операционная система: Ubuntu 22.04 LTS или новее

(Условия прошлых работ - в коммитах с тегами: `git show lab2:task.md`, `git show lab3:task.md`, `git show lab4:task.md`.)

### Цели работы

В ходе выполнения лабораторной работы вы:

- Замерите базовое время ответа эндпоинта `POST /orders/create` при синхронном выполнении тяжёлых операций (генерация PDF, отправка email, SMS).
- Подключите Celery и Redis в качестве брокера сообщений для выполнения фоновых задач.
- Вынесете тяжёлые операции в фон: создание заказа будет мгновенно отвечать клиенту, а PDF, email и SMS — выполняться в отдельных воркерах.
- Настроите ретраи с экспоненциальной задержкой и Dead Letter Queue (DLQ) для обработки ошибок внешних сервисов.
- Реализуете идемпотентность задач, чтобы повторный запуск не создавал дубликаты чеков или писем.
- Проведёте повторные замеры и докажете, что время ответа API сократилось в десятки раз.

Дополнительно (для 9–10 баллов):

- Настроите мониторинг задач через Flower и убедитесь, что задачи видны в реальном времени.
- Реализуете периодические задачи через Celery Beat.

### Критерии оценивания (10-балльная шкала)

| Баллы | Оценка | Что нужно сделать |
|---|---|---|
| 0–3 | Неудовлетворительно (2) | Celery не подключён, фоновые задачи не работают, проект не запускается. Нарушены границы Clean Architecture (задачи вызываются напрямую из роутера, а не из Service). |
| 4–5 | Удовлетворительно (3) | Celery подключён, но вынос задач выполнен частично (например, только PDF, но email остался синхронным). Время ответа API не сократилось. |
| 6–7 | Хорошо (4) | Celery подключён, все тяжёлые операции (PDF, email, SMS) вынесены в фон. Эндпоинт `POST /orders/create` отвечает мгновенно. Проект полностью работоспособен в Swagger. Замеры «до/после» проведены. |
| 8 | Отлично (5) | Все требования уровня 6–7 выполнены. Дополнительно: настроены ретраи с экспоненциальной задержкой и Dead Letter Queue. Реализована идемпотентность (повторный запуск не создаёт дубль). Оформлен `README.md` со сравнительными графиками. Устная защита демонстрирует понимание. |
| 9 | Отлично с плюсом (5+) | Все требования уровня 8 выполнены. Дополнительно: настроен мониторинг задач через Flower. В `README.md` есть скриншоты из Flower, подтверждающие выполнение задач в реальном времени. |
| 10 | Отлично с двойным плюсом (5++) | Все требования уровня 9 выполнены. Дополнительно: реализована периодическая задача через Celery Beat (очистка старых записей или обновление статистики). |

### 1. Пререквизиты

Для выполнения работы вам потребуется:

- Ubuntu 22.04 LTS;
- Python 3.11 или новее;
- Docker Engine и Docker Compose (запущены db и redis);
- Git;
- выполненные лабораторные работы № 2, № 3 и № 4 (архитектура, безопасность, кеширование).

#### Установка дополнительных зависимостей

- `celery` — библиотека для фоновых задач.
- `flower` — веб-интерфейс для мониторинга Celery (для 9 баллов).

```bash
source .venv/bin/activate
pip install celery flower
```

#### Запуск инфраструктуры

Убедимся, что PostgreSQL и Redis запущены (Redis уже используется для кеша и rate limiting):

```bash
docker compose up -d db redis
```

### 2. Теоретическое введение

#### 2.1. Проблема синхронной обработки

Сейчас в «Сириус.Еде» эндпоинт `POST /orders/create` выполняет всё синхронно. В проекте ещё нет реальных операций генерации PDF, отправки email и SMS. Мы добавим их как заглушки с искусственной задержкой (`time.sleep()`), чтобы имитировать тяжёлые операции. Это позволит увидеть проблему синхронности и эффект от внедрения Celery.

Что делает эндпоинт сейчас:

1. Создаёт заказ в PostgreSQL.
2. Имитирует генерацию PDF (`time.sleep(2)`).
3. Имитирует отправку email (`time.sleep(1)`).
4. Имитирует отправку SMS (`time.sleep(1)`).
5. Начисляет бонусы (быстрая операция).

Результат: клиент ждёт 4–5 секунд.

#### 2.2. Что такое фоновая задача

Фоновая задача — это работа, которую можно выполнить после ответа клиенту, в отдельном процессе. Клиент получает ответ за 50 мс, а PDF, email и SMS генерируются в фоне.

Ключевые компоненты Celery:

- Producer — приложение FastAPI, которое ставит задачи.
- Broker — очередь (Redis), где хранятся задачи.
- Worker — отдельный процесс, который забирает задачи из очереди и выполняет их.

Где реализовывать вызов задач: в слое Service. Это бизнес-логика: «после создания заказа — сгенерировать чек и отправить уведомления». Repository и API не должны знать о Celery.

#### 2.3. Почему возникают дубли при ретраях

Когда задача падает, Celery запускает её повторно. Если задача уже частично выполнилась (например, email был отправлен, но упало на следующем шаге), повторный запуск создаст дубль. Идемпотентность решает эту проблему: задача проверяет, была ли она уже выполнена, и пропускает повторную работу.

### 3. Пошаговый разбор внедрения фоновых задач

#### Шаг 1. Замер baseline (10 минут)

Что делаем: замеряем время ответа `POST /orders/create` до внедрения Celery.  
Зачем: чтобы зафиксировать проблему и потом сравнить результат.

Добавьте в `OrderService.create_order()` имитацию тяжёлых операций:

```python
# app/modules/orders/service.py
import time

class OrderService:
    # ... предыдущий код ...

    def create_order(self, customer_id: int, item_id: int, quantity: int) -> Order:
        # ... создание заказа ...
        order = self.repository.save_order(customer_id, item_id, quantity, total)

        # Имитация тяжёлых операций (пока синхронно)
        time.sleep(2)  # генерация PDF
        time.sleep(1)  # отправка email
        time.sleep(1)  # отправка SMS

        return order
```

Замерьте время ответа через curl с командой `time`:

```bash
time curl -X POST "http://127.0.0.1:8000/orders/create" -H "Authorization: Bearer YOUR_TOKEN" -H "Content-Type: application/json" -d '{"item_id": 1, "quantity": 2}'
```

Ожидаемый результат: время ответа около 4 секунд.

#### Шаг 2. Настройка Celery (15 минут)

Что делаем: создаём приложение Celery и подключаем его к Redis.  
Зачем: Celery — это менеджер фоновых задач. Он будет принимать задачи от FastAPI и передавать их воркерам.

Создайте файл `app/core/celery_app.py`:

```python
# app/core/celery_app.py
from celery import Celery
from app.core.config import settings

# Создаём приложение Celery.
# Брокер (Redis) — сюда FastAPI ставит задачи.
# Backend (Redis) — сюда сохраняются результаты выполнения.
celery_app = Celery(
    "sirius_food",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

# Настройки сериализации: JSON вместо pickle (безопаснее).
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)
```

#### Шаг 3. Создание фоновых задач (20 минут)

Что делаем: создаём задачи для генерации PDF и отправки email.  
Зачем: это те операции, которые будут выполняться в фоне.

Создайте файл `app/tasks/orders.py` (и папку `app/tasks/` с `__init__.py`):

```python
# app/tasks/orders.py
import time
from app.core.celery_app import celery_app


@celery_app.task
def generate_order_pdf(order_id: int) -> str:
    """
    Генерация PDF-чека для заказа.
    Имитация тяжёлой операции через time.sleep.
    """
    time.sleep(2)
    return f"PDF generated for order {order_id}"


@celery_app.task
def send_order_email(order_id: int, email: str) -> str:
    """Отправка email о создании заказа."""
    time.sleep(1)
    return f"Email sent to {email} for order {order_id}"


@celery_app.task
def send_order_sms(order_id: int, phone: str) -> str:
    """Отправка SMS о создании заказа."""
    time.sleep(1)
    return f"SMS sent to {phone} for order {order_id}"
```

#### Шаг 4. Вызов задач из Service (15 минут)

Что делаем: заменяем синхронные вызовы на фоновые задачи.  
Зачем: сервис не должен ждать, пока выполнятся тяжёлые операции. Он ставит задачу в очередь и сразу возвращает результат.

Обновите `OrderService.create_order()`:

```python
# app/modules/orders/service.py
from app.tasks.orders import generate_order_pdf, send_order_email, send_order_sms

class OrderService:
    def __init__(self, repository: OrderRepository):
        self.repository = repository

    def create_order(self, customer_id: int, item_id: int, quantity: int) -> Order:
        # ... создание заказа ...
        order = self.repository.save_order(customer_id, item_id, quantity, total)

        # Вызов фоновых задач через .delay()
        # .delay() ставит задачу в очередь и сразу возвращает управление.
        generate_order_pdf.delay(order.id)
        send_order_email.delay(order.id, order.customer.email)
        send_order_sms.delay(order.id, order.customer.phone)

        return order
```

Важно: `service.py` по-прежнему не импортирует fastapi и sqlalchemy. Он вызывает задачи Celery, но это допустимо — это часть бизнес-логики: «после заказа отправить уведомление».

#### Шаг 5. Запуск воркера (10 минут)

Что делаем: запускаем процесс, который будет выполнять задачи.  
Зачем: без воркера задачи будут лежать в очереди и не выполняться.

Откройте новый терминал (воркер должен работать параллельно с FastAPI):

```bash
cd ~/projects/sirius_food
source .venv/bin/activate
celery -A app.core.celery_app worker --loglevel=info
```

Что увидите: воркер подключится к Redis и начнёт слушать очередь. При поступлении задачи он выполнит её.

#### Шаг 6. Повторные замеры (10 минут)

Что делаем: снова замеряем время ответа `POST /orders/create`.  
Зачем: доказать, что API отвечает мгновенно.

1. Убедитесь, что FastAPI и Celery-воркер запущены.
2. Выполните запрос с замером:

```bash
time curl -X POST "http://127.0.0.1:8000/orders/create" -H "Authorization: Bearer YOUR_TOKEN" -H "Content-Type: application/json" -d '{"item_id": 1, "quantity": 2}'
```

Ожидаемый результат: время ответа около 50–100 миллисекунд.

Проверьте логи воркера: он должен показать выполнение трёх задач (`generate_order_pdf`, `send_order_email`, `send_order_sms`).

#### Шаг 7. Ретраи с экспоненциальной задержкой (15 минут)

Что делаем: настраиваем повторный запуск задачи при падении.  
Зачем: если внешний сервис временно недоступен — задача должна повториться через 1, 2, 4 секунды, а не мгновенно.

Обновите задачи в `app/tasks/orders.py`:

```python
@celery_app.task(
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def send_order_email(order_id: int, email: str) -> str:
    """Отправка email с ретраями."""
    time.sleep(1)
    # Имитация падения для каждого 5-го заказа
    if order_id % 5 == 0:
        raise Exception("Email service unavailable")
    return f"Email sent to {email} for order {order_id}"
```

Что это значит:

- `autoretry_for` — при каком исключении повторять.
- `retry_backoff` — экспоненциальная задержка.
- `max_retries` — не более 3 попыток.

Как проверить на сдаче: создайте заказ с `order_id`, кратным 5. В логах воркера будет видно, как задача падает и повторяется с задержкой 1с, 2с, 4с.

#### Шаг 8. Идемпотентность (10 минут)

Что делаем: защищаем задачу от повторного выполнения.  
Зачем: если задача упала и ретрай выполнился дважды, мы не хотим создавать дубль чека или отправлять два email.

Обновите задачу `generate_order_pdf` с проверкой через Redis:

```python
from app.core.redis import redis_client

@celery_app.task(bind=True)
def generate_order_pdf(self, order_id: int) -> str:
    """Генерация PDF с проверкой идемпотентности."""
    # Ключ идемпотентности
    key = f"pdf_generated:{order_id}"

    # Если ключ уже есть — PDF уже сгенерирован, пропускаем
    if redis_client.exists(key):
        return f"PDF already generated for order {order_id}"

    time.sleep(2)

    # Сохраняем флаг на 1 час
    redis_client.setex(key, 3600, "1")

    return f"PDF generated for order {order_id}"
```

Как проверить на сдаче: выполните один и тот же заказ дважды (или вызовите задачу вручную). Второй вызов не должен генерировать PDF заново. В логах воркера будет видно, что задача пропущена.

#### Шаг 9. Dead Letter Queue (DLQ) (10 минут)

Что делаем: настраиваем очередь для задач, которые так и не выполнились после всех ретраев.  
Зачем: чтобы не терять «битые» задачи и иметь возможность разобрать их вручную.

В `app/core/celery_app.py` добавьте:

```python
from kombu import Queue, Exchange

celery_app.conf.task_queues = (
    Queue("default", Exchange("default"), routing_key="default"),
    Queue("dlq", Exchange("dlq"), routing_key="dlq"),
)

celery_app.conf.task_default_queue = "default"
celery_app.conf.task_default_exchange = "default"
celery_app.conf.task_default_routing_key = "default"
```

Как проверить на сдаче: создайте заказ с `order_id`, кратным 5. После 3 неудачных попыток задача будет помечена как failed. В логах воркера будет видно сообщение о превышении `max_retries`. Для просмотра очереди DLQ используйте `redis-cli -n 0 lrange dlq 0 -1`.

### 4. Задание для самостоятельной работы

Вам необходимо доработать систему фоновых задач:

1. Мониторинг через Flower (9 баллов).
   - Запустите Flower: `celery -A app.core.celery_app flower`.
   - Откройте http://localhost:5555, убедитесь, что задачи видны в реальном времени.
   - Сделайте скриншоты для `README.md`.
2. Celery Beat (10 баллов).
   - Настройте периодическую задачу, которая выполняется раз в минуту. Например:
     - Очистка старых записей в таблице `task_logs` (удаление записей старше 30 дней).
     - Обновление статистики — подсчёт количества заказов за день и запись в отдельную таблицу (или в Redis).
   - Используйте `celery_app.conf.beat_schedule`.
3. Оформите отчет.
   - Подготовьте `README.md` со сравнительной таблицей «До / После» (время ответа API).
   - Приложите скриншоты из Flower.

Задание сдаётся в виде:

- очной демонстрации на вашем ноутбуке;
- файла `README.md` с графиками и скриншотами;
- устной защиты.

### 5. Контрольные вопросы для защиты работы

1. Почему вызов фоновых задач реализован в слое Service, а не в Router? Как это связано с Clean Architecture?
2. Что произойдёт, если Celery-воркер отключится во время выполнения задачи?
3. Что такое идемпотентность и почему она важна для фоновых задач?
4. Зачем нужны ретраи с экспоненциальной задержкой?
5. Что такое Dead Letter Queue и как её использовать?
6. Почему Celery — стандарт индустрии, а не просто threading или asyncio?
7. Чем Celery Beat отличается от обычной задачи?

### 6. Приложение: Структура проекта после внедрения

```text
app/
├── core/
│   ├── celery_app.py     # Настройка Celery
│   ├── redis.py          # Клиент Redis
│   └── ...
├── tasks/                # Фоновые задачи
│   ├── __init__.py
│   └── orders.py         # generate_order_pdf, send_order_email, send_order_sms
├── modules/
│   └── orders/
│       ├── router.py     # Без изменений
│       ├── service.py    # Добавлены вызовы задач через .delay()
│       ├── repository.py
│       └── exceptions.py
```

Ключевой результат: `service.py` не импортирует FastAPI и SQLAlchemy. Он вызывает задачи Celery, но бизнес-логика остаётся чистой.
