# Лабораторная работа № 4

## Кеширование в продакшн: внедрение Cache-Aside на Redis

Дисциплина: Разработка программных модулей и приложений для серверов  
Тема: Кеширование в продакшн: стратегия Cache-Aside, инвалидация, замеры нагрузки  
Продолжительность: 2 академических часа (90 минут) + самостоятельная работа  
Проект: сквозной пет-проект «Сириус.Еда»  
Операционная система: Ubuntu 22.04 LTS или новее

(Условия прошлых работ - в коммитах с тегами: `git show lab2:task.md`, `git show lab3:task.md`.)

### Цели работы

В ходе выполнения лабораторной работы вы:

- Замерите базовую нагрузку на PostgreSQL при 500 одновременных запросах к меню (симуляция обеденного перерыва).
- Подключите Redis к проекту и настроите клиент для работы с кешем.
- Реализуете стратегию Cache-Aside для чтения меню в инфраструктурном слое (Repository).
- Настроите инвалидацию кеша (событийную и по TTL) при изменении данных.
- Проведёте повторные замеры и докажете, что кеш снял нагрузку с СУБД.

Дополнительно (для 9–10 баллов):

- Реализуете защиту от cache stampede (блокировка или вероятностное обновление).
- Добавите кеширование для категорий меню (`menu:category:{id}`).

### Критерии оценивания (10-балльная шкала)

| Баллы | Оценка | Что нужно сделать |
|---|---|---|
| 0–3 | Неудовлетворительно (2) | Redis не подключён, кеширование не работает, проект не запускается. Нарушены границы Clean Architecture (кеш в Service вместо Repository). |
| 4–5 | Удовлетворительно (3) | Redis подключён, но Cache-Aside реализован с ошибками (например, неверный TTL или отсутствие проверки на hit/miss). Замеры не проведены. |
| 6–7 | Хорошо (4) | Cache-Aside реализован корректно в Repository. TTL установлен. Инвалидация при обновлении меню работает. Проект полностью работоспособен в Swagger. Замеры Locust проведены. |
| 8 | Отлично (5) | Все требования уровня 6–7 выполнены. Дополнительно: оформлен README.md со сравнительными графиками «до/после» (RPS, latency). Устная защита демонстрирует понимание. |
| 9 | Отлично с плюсом (5+) | Все требования уровня 8 выполнены. Дополнительно: реализована защита от cache stampede (через блокировку Redis или asyncio.Lock). |
| 10 | Отлично с двойным плюсом (5++) | Все требования уровня 9 выполнены. Дополнительно: закешированы категории меню с разными TTL, либо реализован прогрев кеша (cache warm-up) при старте приложения. |

### 1. Пререквизиты

Для выполнения работы вам потребуется:

- Ubuntu 22.04 LTS;
- Python 3.11 или новее;
- Docker Engine и Docker Compose (запущены db и redis);
- Git;
- выполненные лабораторные работы № 2 и № 3 (модули отрефакторены, внедрена безопасность).

#### Установка дополнительных зависимостей

- `redis` — клиент для подключения к Redis из Python.
- `locust` — инструмент для нагрузочного тестирования.

```bash
source .venv/bin/activate
pip install redis locust
```

#### Запуск инфраструктуры

Убедимся, что PostgreSQL и Redis запущены (Redis уже используется для rate limiting в ЛР № 3):

```bash
docker compose up -d db redis
```

### 2. Теоретическое введение

#### 2.1. Проблема чтения в пиковые часы

В «Сириус.Еде» эндпоинт `GET /menu/items` вызывается очень часто. Меню меняется раз в день, но читается сотни раз в минуту. Без кеша каждый запрос идёт в PostgreSQL, выполняя тяжёлый SQL-запрос с JOIN категорий и сортировкой. При 500 одновременных запросах пул соединений переполняется, время ответа растёт с миллисекунд до секунд.

#### 2.2. Стратегия Cache-Aside

Самый популярный подход. Алгоритм:

1. Приложение ищет данные в кеше.
2. Если находит (hit) — возвращает их.
3. Если не находит (miss) — идёт в БД, сохраняет результат в кеш и возвращает клиенту.

Где реализовывать: в слое Repository. Кеш — это деталь хранения данных (инфраструктура). Бизнес-логика (Service) не должна знать, откуда пришли данные: из БД или из Redis. Если положить кеш в Service, вы нарушите принципы Clean Architecture.

### 3. Пошаговый разбор внедрения кеширования

#### Шаг 1. Замер baseline (15 минут)

Что делаем: запускаем нагрузочное тестирование на эндпоинт `GET /menu/items` до внедрения кеша.  
Зачем: чтобы зафиксировать проблему и потом сравнить результат.

Создайте файл `locustfile.py` в корне проекта:

```python
# locustfile.py
from locust import HttpUser, task, between

class MenuUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task
    def get_menu(self):
        # Запрос к меню. Если в ЛР № 3 добавлена защита,
        # возможно, потребуется передать токен. Для чистоты замера
        # лучше временно сделать эндпоинт публичным или замокать токен.
        self.client.get("/menu/items")
```

Запустите Locust:

```bash
locust -f locustfile.py --host=http://127.0.0.1:8000
```

Откройте http://localhost:8089, укажите 500 пользователей и 10 пользователей в секунду (spawn rate).  
Зафиксируйте результаты (RPS, среднее время ответа, 95-й перцентиль).

Ожидаемый результат: время ответа 1–2 секунды, RPS низкий, PostgreSQL загружен.

#### Шаг 2. Подключение Redis (10 минут)

Что делаем: создаём клиент Redis.  
Зачем: приложению нужен интерфейс для работы с кешем.

Создайте файл `app/core/redis.py`:

```python
# app/core/redis.py
import redis
from app.core.config import settings

# Клиент Redis. decode_responses=True означает, что мы получаем строки,
# а не байты — удобно для JSON.
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)


def check_redis_connection() -> bool:
    """Проверка соединения с Redis."""
    try:
        return redis_client.ping()
    except redis.ConnectionError:
        return False
```

Проверка: выполните в терминале Python:

```python
from app.core.redis import redis_client
print(redis_client.ping())  # Должно вывести True
```

#### Шаг 3. Реализация Cache-Aside в Repository (25 минут)

Что делаем: добавляем проверку кеша в слой инфраструктуры (`MenuRepository`).  
Зачем: кеш — это замена/ускоритель БД. Бизнес-логика (Service) не должна меняться.

Откройте `app/modules/menu/repository.py`. Добавьте логику кеширования:

```python
# app/modules/menu/repository.py
import json
from sqlalchemy.orm import Session
from app.models import MenuItem
from app.core.redis import redis_client


class MenuRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_all(self) -> list[MenuItem]:
        """
        Возвращает всё меню.
        Сначала проверяет кеш Redis (Cache-Aside).
        При промахе (miss) идёт в БД и кеширует результат.
        """
        cache_key = "menu:all"

        # 1. Проверка кеша
        cached_data = redis_client.get(cache_key)
        if cached_data:
            # Hit: возвращаем данные из кеша
            items_data = json.loads(cached_data)
            # Восстанавливаем объекты модели из словарей (если нужно для роутера)
            return [MenuItem(**item) for item in items_data]

        # 2. Miss: идём в БД
        items = self.db.query(MenuItem).all()

        # 3. Сохраняем в кеш с TTL 5 минут (300 секунд)
        items_json = json.dumps([{"id": i.id, "name": i.name, "price": i.price} for i in items])
        redis_client.setex(cache_key, 300, items_json)

        return items

    def get_by_id(self, item_id: int) -> MenuItem | None:
        # Для точечного чтения по ID можно использовать другой ключ
        return self.db.query(MenuItem).filter(MenuItem.id == item_id).first()
```

Важно: в `router.py` или `service.py` метод `get_all` вызывается как обычно. Внешне ничего не изменилось, но теперь данные приходят из Redis.

#### Шаг 4. Инвалидация кеша (15 минут)

Что делаем: при обновлении или создании блюда удаляем ключ `menu:all` из Redis.  
Зачем: иначе пользователи будут видеть старое меню до истечения TTL (5 минут). Это событийная инвалидация.

Откройте `app/modules/menu/repository.py`. Добавьте метод удаления кеша:

```python
# app/modules/menu/repository.py
class MenuRepository:
    # ... предыдущий код ...

    def invalidate_cache(self) -> None:
        """Сбрасывает кеш меню."""
        redis_client.delete("menu:all")
```

Теперь обновите `MenuService`. В методах `create_item` и `update_item` после сохранения вызывайте `invalidate_cache`:

```python
# app/modules/menu/service.py
class MenuService:
    def __init__(self, repository: MenuRepository):
        self.repository = repository

    def create_item(self, name: str, price: float) -> MenuItem:
        if self.repository.get_by_name(name):
            raise MenuItemNameExistsError()
        item = MenuItem(name=name, price=price, is_available=True)
        saved_item = self.repository.save(item)
        # Инвалидация кеша: меню изменилось
        self.repository.invalidate_cache()
        return saved_item

    def update_item(self, item_id: int, name: str | None, price: float | None, is_available: bool | None) -> MenuItem:
        item = self.repository.get_by_id(item_id)
        if not item:
            raise MenuItemNotFoundError()
        if name is not None:
            item.name = name
        if price is not None:
            item.price = price
        if is_available is not None:
            item.is_available = is_available
        saved_item = self.repository.save(item)
        # Инвалидация кеша: меню изменилось
        self.repository.invalidate_cache()
        return saved_item
```

Проверка:

1. Сделайте запрос `GET /menu/items` (данные уйдут в кеш).
2. Создайте новое блюдо через `POST /menu/items`.
3. Снова запросите `GET /menu/items` — новое блюдо должно появиться сразу.

#### Шаг 5. Повторные замеры (15 минут)

Что делаем: запускаем Locust с теми же параметрами (500 пользователей).  
Зачем: доказать, что кеш работает.

1. Снова запустите Locust.
2. Зафиксируйте результаты.

Ожидаемый результат: время ответа 2–5 миллисекунд, RPS вырос в десятки раз, PostgreSQL почти не получает запросов.

#### Шаг 6. Рефлексия (10 минут)

Обсудите со студентами:

- Что произойдёт, если TTL истечёт во время пиковой нагрузки? (Cache stampede).
- Как изменится поведение, если меню будет меняться каждую минуту?
- Что будет, если Redis упадёт? (Приложение продолжит работать, но медленно, так как все запросы пойдут в БД).

### 4. Задание для самостоятельной работы

Вам необходимо доработать кеширование для оставшихся сущностей и решить проблемы:

1. Кеширование категорий меню.
   - Создайте эндпоинт `GET /menu/categories/{id}` (или группировку по категориям).
   - Закешируйте данные с ключом `menu:category:{id}` и TTL 10 минут.
2. Защита от cache stampede.
   - Реализуйте блокировку (например, через `redis.lock` или `asyncio.Lock`).
   - При промахе только один запрос идёт в БД, остальные ждут и получают результат из обновлённого кеша.
3. Прогрев кеша (Cache Warm-Up).
   - При старте приложения (startup event в FastAPI) заполните `menu:all` данными из БД, чтобы первый запрос не шёл в базу.
4. Оформите отчет.
   - Подготовьте `README.md` со сравнительной таблицей «До / После» (RPS, Latency, Load Average).

Задание сдаётся в виде:

- репозитория Git с историей коммитов;
- файла `README.md` с графиками (можно скриншотами из Locust);
- устной защиты.

### 5. Контрольные вопросы для защиты работы

1. Почему логика кеширования реализована в слое Repository, а не в Service? Как это связано с Clean Architecture?
2. Что такое Cache-Aside и какие у этой стратегии есть недостатки?
3. Что произойдёт, если Redis перезагрузится во время пиковой нагрузки? Как это называется?
4. Почему для меню выбран TTL 5 минут, а не 1 час?
5. Как событийная инвалидация дополняет инвалидацию по TTL?
6. Какие данные в «Сириус.Еде» категорически нельзя кешировать и почему?
7. Как бы вы решили проблему cache stampede, если бы кеш хранил 10 000 ключей?

### 6. Приложение: Структура проекта после внедрения

```text
app/
├── core/
│   ├── config.py
│   ├── redis.py          # Клиент Redis
│   └── ...
├── modules/
│   └── menu/
│       ├── router.py     # Без изменений (или минимальные)
│       ├── service.py    # Добавлен вызов invalidate_cache
│       ├── repository.py # Добавлены get_all с кешем и invalidate_cache
│       └── exceptions.py
```

Ключевой результат: `service.py` по-прежнему не импортирует redis. Бизнес-логика осталась чистой.
