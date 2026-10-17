# Лабораторная работа 2. Рефакторинг MVP-модулей в Clean Architecture

## Задание

Есть проект «Сириус.Еда» (FastAPI + SQLAlchemy + PostgreSQL), где в каждом `router.py` всё смешано: HTTP, бизнес-проверки и SQL. Нужно разделить модули на три слоя:

- `router.py` - транспортный слой (HTTP, техническая валидация, перевод ошибок в HTTP-статусы);
- `service.py` - бизнес-логика, без импортов `fastapi` и `sqlalchemy`;
- `repository.py` - работа с БД.

Репозиторий передаётся в сервис через конструктор. API после рефакторинга должно отвечать так же, как до него. Полный текст задания - в [task.md](task.md).

## Что сделано

- `orders` - отрефакторен по шаблону из методички.
- `users` и `menu` - отрефакторены самостоятельно по тому же шаблону.
- `delivery` - дополнительно отрефакторен так же (синхронно, без async).
- Во всех четырёх модулях в `repository.py` выделен абстрактный класс (ABC) и две реализации: PostgreSQL и in-memory.
- Реализация выбирается переменной окружения `REPOSITORY`. Подмена хранилища не требует менять `service.py` и `router.py`.
- 19 unit-тестов на `service.py` всех четырёх модулей. СУБД для них не нужна.

## Как запустить

PostgreSQL и Redis:

```bash
docker compose up -d db redis
```

Окружение. Версии в `requirements.txt` закреплены старые (pydantic 2.6, psycopg2 2.9.9), под Python 3.13+ они не собираются, поэтому нужен Python 3.11 или 3.12:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Сервер (Swagger на http://127.0.0.1:8000/docs):

```bash
uvicorn app.main:app --reload
```

Тот же сервер, но все данные в памяти, PostgreSQL не нужен:

```bash
REPOSITORY=memory uvicorn app.main:app --reload
```

Unit-тесты:

```bash
python -m unittest discover tests -v
```

## Структура после рефакторинга

```text
app/
├── main.py            # точка входа; создаёт таблицы только в режиме postgres
├── config.py          # НОВЫЙ: REPOSITORY = postgres | memory
├── database.py        # добавлен echo=True (SQL-логи в терминале)
├── exceptions.py      # НОВЫЙ: NotFoundError, ForbiddenError
├── memory_db.py       # НОВЫЙ: хранилище в памяти для in-memory репозиториев
├── models.py          # без изменений
├── schemas.py         # без изменений
└── modules/
    ├── orders/
    │   ├── __init__.py
    │   ├── router.py      # транспортный слой
    │   ├── service.py     # бизнес-логика
    │   └── repository.py  # ABC + PostgreSQL + in-memory
    ├── users/             # то же самое
    ├── menu/              # то же самое
    └── delivery/          # то же самое
tests/
└── test_services.py   # НОВЫЙ: unit-тесты сервисов без БД
```

## Схема пути запроса через слои

На примере `POST /orders/create`:

```text
Клиент (Swagger / curl)
   |  POST /orders/create  {"user_id": 1, "item_id": 1, "quantity": 2}
   v
+---------------------------------------------------------------+
| router.py   (API Layer / Frameworks & Drivers)                |
|  1. Pydantic проверяет типы полей (схема OrderCreate)         |
|  2. quantity <= 0 ?  -> HTTP 400                              |
|  3. repository = get_order_repository(db)                     |
|     service = OrderService(repository)                        |
+---------------------------------------------------------------+
   |  service.create_order(user_id=1, item_id=1, quantity=2)
   v
+---------------------------------------------------------------+
| service.py  (Business Logic / Entities + Use Cases)           |
|  пользователь есть? блюдо есть? доступно? хватает денег?      |
|  -> списать деньги, сохранить заказ                           |
|  ошибки: NotFoundError, ValueError                            |
+---------------------------------------------------------------+
   |  get_user_by_id, get_menu_item_by_id,
   |  update_user_balance, save_order
   v
+---------------------------------------------------------------+
| repository.py  (Infrastructure / Interface Adapters)          |
|  OrderRepository (ABC)                                        |
|   |-- PostgresOrderRepository -> SQLAlchemy -> PostgreSQL     |
|   `-- InMemoryOrderRepository -> app/memory_db.py             |
+---------------------------------------------------------------+

Обратно:  repository -> order_id -> service -> router -> {"status": "success", "order_id": 1}
Ошибка:   service бросает NotFoundError -> router превращает её в HTTP 404
```

Направление зависимостей (кто кого импортирует):

```text
router.py  --->  service.py  --->  OrderRepository (абстракция)
    |                                    ^           ^
    |                                    |           |
    +--> get_order_repository()   PostgresOrder...  InMemoryOrder...
```

Сервис знает только абстракцию. Какая реализация придёт - решает фабрика `get_order_repository()` в `repository.py`.

## Что изменилось по сравнению с MVP

Раньше весь код модуля был в одной функции роутера. Теперь:

- SQL-запросы и `db.add/commit/refresh` переехали в `repository.py`;
- бизнес-проверки (существует ли пользователь, хватает ли денег, уникален ли email и т.д.) переехали в `service.py`;
- в `router.py` осталась только техническая проверка входных данных, сборка слоёв, вызов сервиса и перевод исключений в HTTP-коды.

Что сделал не так, как в примере из методички, и почему:

1. Импорты `from models import ...` и `from orders.repository import ...` заменил на `from app.models ...` и `from app.modules.orders...` - в проекте все модули лежат внутри пакета `app`, иначе не запустится.
2. В примере роутер объявлен как `@router.post("/orders/create")`. В `main.py` у роутера уже есть `prefix="/orders"`, получилось бы `/orders/orders/create`. Оставил `/create`, как в исходном коде.
3. В примере сервис бросает только `ValueError`, и роутер всё отдаёт как 400. В MVP «не найдено» было 404, а «заблокирован» - 403, и тексты ошибок в примере тоже другие. По заданию ответы должны остаться идентичными, поэтому добавил `app/exceptions.py` с `NotFoundError` (404) и `ForbiddenError` (403), а тексты ошибок оставил исходные.
4. Статус нового заказа `"processing"`, нулевой баланс нового пользователя и `is_available=True` у нового блюда задаёт сервис, а не репозиторий. Это бизнес-правила. К тому же реализаций репозитория две, и иначе правило пришлось бы дублировать в обеих.
5. В `database.py` добавил `echo=True`, иначе SQL-логов из п.5 задания в терминале не видно.

Порядок проверок: техническая валидация теперь всегда выполняется раньше бизнес-проверок. Разница видна, только если в запросе сразу две ошибки:

- регистрация с занятым email и коротким телефоном: было «уже зарегистрирован», стало «Некорректный формат номера телефона» (оба 400);
- `PATCH /menu/items/99` с ценой `-1`: было 404 «Блюдо не найдено», стало 400 «Цена должна быть положительной».

Во всех остальных случаях ответы одинаковые - проверено скриптом на 26 запросах (результат ниже).

## Разбор кода

### app/exceptions.py

Два своих исключения: `NotFoundError` и `ForbiddenError`. Для остальных нарушений бизнес-правил используется обычный `ValueError`, как в методичке. Сервис ничего не знает про HTTP, он просто бросает исключение, а роутер решает, какой это код:

- `NotFoundError` -> 404
- `ForbiddenError` -> 403
- `ValueError` -> 400

### app/config.py

Одна настройка `REPOSITORY`, читается из переменной окружения. По умолчанию `postgres`.

### app/memory_db.py

Хранилище для in-memory репозиториев: четыре словаря (`users`, `menu_items`, `orders`, `deliveries`) вида `id -> запись` и dataclass'ы для записей. Словари общие для всех модулей, поэтому в memory-режиме заказ видит пользователей и блюда, созданные через `/users` и `/menu`, а доставка видит заказы. Функция `clear()` очищает данные перед каждым тестом.

### repository.py (на примере orders)

- `OrderRepository(ABC)` - интерфейс: какие операции с данными нужны сервису (`get_user_by_id`, `get_menu_item_by_id`, `save_order`, `update_user_balance`). Методы помечены `@abstractmethod`, поэтому нельзя создать реализацию, которая забыла какой-то метод.
- `PostgresOrderRepository` - тот же код, что был в MVP-роутере: `db.query(...)`, `db.add`, `db.commit`, `db.refresh`.
- `InMemoryOrderRepository` - то же самое, но со словарями из `memory_db.py`.
- `get_order_repository(db)` - фабрика: по `config.REPOSITORY` возвращает нужную реализацию. Это единственное место, где выбирается хранилище.

В `users/repository.py` и `menu/repository.py` всё устроено так же.

### service.py (на примере orders)

`OrderService` получает репозиторий в конструкторе и работает только с его методами. Метод `create_order`:

1. берёт пользователя, нет - `NotFoundError`;
2. берёт блюдо, нет - `NotFoundError`;
3. блюдо недоступно - `ValueError`;
4. считает сумму, денег не хватает - `ValueError`;
5. через репозиторий списывает деньги и сохраняет заказ, возвращает `order_id`.

В файле нет `fastapi` и `sqlalchemy`, поэтому сервис можно вызвать откуда угодно: из теста, из CLI, из фоновой задачи.

### router.py (на примере orders)

1. FastAPI с Pydantic проверяют тело запроса по схеме `OrderCreate`.
2. Роутер проверяет `quantity > 0` (техническая проверка).
3. Собирает слои: `OrderService(get_order_repository(db))`.
4. Вызывает сервис и ловит исключения: `NotFoundError` -> 404, `ValueError` -> 400.
5. Возвращает тот же JSON, что и раньше.

### users

- формат email - Pydantic (`EmailStr` в схеме), транспортный слой;
- длина телефона >= 10 и сумма пополнения > 0 - `router.py`, техническая валидация;
- уникальность email, «пользователь не найден», «заблокирован», лимит 50000 за одно пополнение, нулевой баланс нового пользователя - `service.py`.

Лимит вынесен в константу `MAX_TOP_UP`.

### menu

- цена > 0 и длина названия >= 2 - `router.py`;
- уникальность названия, «блюдо не найдено», новое блюдо сразу доступно - `service.py`;
- `update_item` в сервисе меняет только те поля, которые пришли (не `None`), и сохраняет блюдо через `repository.update_item`.

### delivery

Технической валидации в MVP тут не было, поэтому роутер только собирает слои и переводит исключения в HTTP-коды (404, 403, 400). Все проверки - бизнес-правила, они в `service.py`:

- `assign_courier`: заказ существует; заказ оплачен (`status == "paid"`); курьер существует; курьер не заблокирован; у курьера нет доставки в статусе `in_progress` («один курьер - одна активная доставка»). Новая доставка создаётся со статусом `in_progress`.
- `complete_delivery`: доставка существует; не завершена; не отменена. Затем доставка получает статус `completed`, а её заказ - `delivered`.

Какой статус считается активным, решает сервис: он передаёт `"in_progress"` в метод репозитория `get_courier_delivery_by_status`. Репозиторий просто ищет по курьеру и статусу и правил не знает.

При завершении доставки оба статуса сохраняются методом `update_delivery_and_order` одним commit, как в MVP. Если заказ сохранится, а доставка нет, данные разъедутся, поэтому здесь одна транзакция.

Особенность исходного проекта: в API нет эндпоинта, который переводит заказ в статус `paid` (новые заказы получают `processing`). Поэтому назначить курьера можно только после того, как статус заказа поменяли в БД вручную. Я это не менял, так как задача - рефакторинг без изменения поведения.

### main.py

Добавлено условие: `Base.metadata.create_all` вызывается только при `REPOSITORY=postgres`. Иначе в memory-режиме сервер падал бы на старте, пытаясь подключиться к БД.

### tests/test_services.py

Обычный `unittest`, никаких дополнительных библиотек. В каждом тесте `setUp` очищает `memory_db`, при необходимости кладёт туда пользователя и блюда и создаёт сервис с in-memory репозиторием. Проверяются:

- orders: успешный заказ списывает баланс; при нехватке денег баланс и заказы не меняются; недоступное блюдо; нет пользователя;
- users: нулевой баланс при регистрации; повторный email; пополнение; лимит 50000; заблокированный пользователь;
- menu: повторное название; изменение только переданных полей; блюдо не найдено;
- delivery: назначение курьера; неоплаченный заказ; заблокированный курьер; курьер уже занят; завершение доставки меняет статус заказа на `delivered`; повторное завершение; доставка не найдена.

## Что происходит при запуске

1. `uvicorn` импортирует `app.main`.
2. `config.py` читает `REPOSITORY` (по умолчанию `postgres`).
3. В режиме `postgres` создаются таблицы в БД.
4. Подключаются роутеры четырёх модулей с префиксами `/users`, `/menu`, `/orders`, `/delivery`.
5. Пришёл запрос, например `POST /orders/create`:
   - FastAPI проверяет тело по схеме и через `Depends(get_db)` открывает сессию БД;
   - роутер делает техническую проверку и собирает репозиторий и сервис;
   - сервис проверяет бизнес-правила и через репозиторий читает и пишет данные;
   - роутер возвращает JSON или переводит исключение в HTTP-ошибку;
   - после ответа `get_db` закрывает сессию.

В memory-режиме сессия тоже создаётся, но к БД не подключается: SQLAlchemy подключается только при первом запросе к базе, а in-memory репозиторий её не трогает.

## Пример вывода

Unit-тесты (PostgreSQL при этом был остановлен):

```text
$ python -m unittest discover tests -v
test_assign_blocked_courier (test_services.DeliveryServiceTest.test_assign_blocked_courier) ... ok
test_assign_courier (test_services.DeliveryServiceTest.test_assign_courier) ... ok
test_assign_to_unpaid_order (test_services.DeliveryServiceTest.test_assign_to_unpaid_order) ... ok
test_complete_delivery_marks_order_delivered (test_services.DeliveryServiceTest.test_complete_delivery_marks_order_delivered) ... ok
test_complete_not_found (test_services.DeliveryServiceTest.test_complete_not_found) ... ok
test_complete_twice (test_services.DeliveryServiceTest.test_complete_twice) ... ok
test_courier_already_busy (test_services.DeliveryServiceTest.test_courier_already_busy) ... ok
test_create_duplicate_name (test_services.MenuServiceTest.test_create_duplicate_name) ... ok
test_update_not_found (test_services.MenuServiceTest.test_update_not_found) ... ok
test_update_only_given_fields (test_services.MenuServiceTest.test_update_only_given_fields) ... ok
test_create_order_writes_off_balance (test_services.OrderServiceTest.test_create_order_writes_off_balance) ... ok
test_not_enough_money (test_services.OrderServiceTest.test_not_enough_money) ... ok
test_unavailable_item (test_services.OrderServiceTest.test_unavailable_item) ... ok
test_user_not_found (test_services.OrderServiceTest.test_user_not_found) ... ok
test_register_duplicate_email (test_services.UserServiceTest.test_register_duplicate_email) ... ok
test_register_with_zero_balance (test_services.UserServiceTest.test_register_with_zero_balance) ... ok
test_top_up (test_services.UserServiceTest.test_top_up) ... ok
test_top_up_blocked_user (test_services.UserServiceTest.test_top_up_blocked_user) ... ok
test_top_up_over_limit (test_services.UserServiceTest.test_top_up_over_limit) ... ok

----------------------------------------------------------------------
Ran 19 tests in 0.000s

OK
```

Ответы API. Один и тот же набор из 26 запросов прогнал на MVP-версии и на отрефакторенной (обе на чистой БД), `diff` ничего не показал. Часть вывода (`метод путь тело -> ответ [HTTP-код]`):

```text
POST /users/register {"email":"ivan@sirius.ru","phone":"+79991234567"} -> {"status":"success","user_id":1,"email":"ivan@sirius.ru"} [200]
POST /users/register {"email":"ivan@sirius.ru","phone":"+79991234567"} -> {"detail":"Пользователь с таким email уже зарегистрирован"} [400]
POST /users/register {"email":"petr@sirius.ru","phone":"123"} -> {"detail":"Некорректный формат номера телефона"} [400]
POST /users/1/topup?amount=1000  -> {"status":"success","new_balance":1000.0} [200]
POST /users/1/topup?amount=60000  -> {"detail":"Максимальная сумма пополнения — 50000 рублей"} [400]
POST /users/99/topup?amount=100  -> {"detail":"Пользователь не найден"} [404]
POST /users/2/topup?amount=100  -> {"detail":"Пользователь заблокирован. Пополнение невозможно"} [403]
POST /menu/items {"name":"Борщ","price":250} -> {"status":"success","item_id":1} [200]
POST /menu/items {"name":"Борщ","price":300} -> {"detail":"Блюдо с таким названием уже существует"} [400]
PATCH /menu/items/99 {"name":"Суп"} -> {"detail":"Блюдо не найдено"} [404]
PATCH /menu/items/1 {"name":"Борщ с говядиной","price":270} -> {"status":"success","item_id":1} [200]
POST /orders/create {"user_id":1,"item_id":1,"quantity":2} -> {"status":"success","order_id":1} [200]
POST /orders/create {"user_id":1,"item_id":1,"quantity":0} -> {"detail":"Количество должно быть больше нуля"} [400]
POST /orders/create {"user_id":99,"item_id":1,"quantity":1} -> {"detail":"Пользователь не найден"} [404]
POST /orders/create {"user_id":1,"item_id":2,"quantity":1} -> {"detail":"Блюдо недоступно"} [400]
POST /orders/create {"user_id":1,"item_id":1,"quantity":10} -> {"detail":"Недостаточно средств на балансе студента"} [400]
POST /users/1/topup?amount=0.5  -> {"status":"success","new_balance":460.5} [200]
```

Последняя строка показывает, что заказ списал деньги: 1000 - 2 * 270 = 460, плюс 0.5.

SQL-лог успешного заказа (п.5 задания: видны `UPDATE` и `INSERT`):

```text
INFO sqlalchemy.engine.Engine SELECT users.id AS users_id, ... FROM users WHERE users.id = %(id_1)s LIMIT %(param_1)s
INFO sqlalchemy.engine.Engine SELECT menu_items.id AS menu_items_id, ... FROM menu_items WHERE menu_items.id = %(id_1)s LIMIT %(param_1)s
INFO sqlalchemy.engine.Engine UPDATE users SET balance=%(balance)s WHERE users.id = %(users_id)s
INFO sqlalchemy.engine.Engine [cached since 0.144s ago] {'balance': 460.0, 'users_id': 1}
INFO sqlalchemy.engine.Engine COMMIT
INFO sqlalchemy.engine.Engine INSERT INTO orders (user_id, item_id, quantity, status) VALUES (...) RETURNING orders.id
INFO sqlalchemy.engine.Engine [generated in 0.00008s] {'user_id': 1, 'item_id': 1, 'quantity': 2, 'status': 'processing'}
INFO sqlalchemy.engine.Engine COMMIT
INFO:     127.0.0.1:50596 - "POST /orders/create HTTP/1.1" 200 OK
```

Режим `REPOSITORY=memory` при остановленном PostgreSQL: сервер стартует, в логе ни одного SQL-запроса. На тех же 26 запросах отличается один ответ: в первом прогоне пользователя 2 блокировали SQL-командой в PostgreSQL, а в памяти так сделать нельзя, поэтому вместо 403 пополнение проходит:

```text
INFO:     Uvicorn running on http://127.0.0.1:8001 (Press CTRL+C to quit)
INFO:     127.0.0.1:47316 - "POST /users/register HTTP/1.1" 200 OK
INFO:     127.0.0.1:47324 - "POST /users/register HTTP/1.1" 400 Bad Request
...
```

Delivery проверял отдельным сценарием. В нём сначала через API создаются клиент, два курьера, блюдо и три заказа, затем SQL-командой заказы 1 и 2 становятся `paid`, а курьер 3 блокируется. Ответы MVP-версии и отрефакторенной совпали, итоговые статусы в БД тоже:

```text
POST /delivery/assign {"order_id":99,"courier_id":2} -> {"detail":"Заказ не найден"} [404]
POST /delivery/assign {"order_id":3,"courier_id":2} -> {"detail":"Курьера можно назначить только на оплаченный заказ"} [400]
POST /delivery/assign {"order_id":1,"courier_id":99} -> {"detail":"Курьер не найден"} [404]
POST /delivery/assign {"order_id":1,"courier_id":3} -> {"detail":"Курьер заблокирован и не может быть назначен"} [403]
POST /delivery/assign {"order_id":1,"courier_id":2} -> {"status":"success","delivery_id":1} [200]
POST /delivery/assign {"order_id":2,"courier_id":2} -> {"detail":"У курьера уже есть активная доставка"} [400]
PATCH /delivery/99/complete  -> {"detail":"Доставка не найдена"} [404]
PATCH /delivery/1/complete  -> {"status":"success"} [200]
PATCH /delivery/1/complete  -> {"detail":"Доставка уже завершена"} [400]
POST /delivery/assign {"order_id":1,"courier_id":2} -> {"detail":"Курьера можно назначить только на оплаченный заказ"} [400]
POST /delivery/assign {"order_id":2,"courier_id":2} -> {"status":"success","delivery_id":2} [200]
PATCH /delivery/2/complete  -> {"detail":"Отменённую доставку нельзя завершить"} [400]
orders: 1=delivered 2=paid 3=processing
deliveries: 1=completed/courier2 2=cancelled/courier2
```

Перед последним `complete` доставку 2 отменили SQL-командой: эндпоинта для отмены в проекте нет.

SQL-лог завершения доставки: оба UPDATE в одной транзакции.

```text
INFO sqlalchemy.engine.Engine UPDATE orders SET status=%(status)s WHERE orders.id = %(orders_id)s
INFO sqlalchemy.engine.Engine UPDATE deliveries SET status=%(status)s WHERE deliveries.id = %(deliveries_id)s
INFO sqlalchemy.engine.Engine [generated in 0.00010s] {'status': 'completed', 'deliveries_id': 1}
INFO sqlalchemy.engine.Engine COMMIT
INFO:     127.0.0.1:57234 - "PATCH /delivery/1/complete HTTP/1.1" 200 OK
```

## Ответы на контрольные вопросы

**1. Какому кругу модели Мартина соответствует repository.py?**
Кругу 3, Interface Adapters. Репозиторий - адаптер: переводит вызовы сервиса на языке предметной области (`save_order`, `get_user_by_id`) в операции конкретного хранилища (SQL через ORM или словарь в памяти). Бизнес-правил в нём нет, сама СУБД и драйвер находятся снаружи, в круге 4.

**2. Почему в service.py нельзя импортировать fastapi и sqlalchemy?**
Соблюдается правило зависимостей: зависимости направлены только внутрь, и внутренний слой не знает о внешних. FastAPI и SQLAlchemy - внешние детали (веб и БД). Если сервис их импортирует, бизнес-логика привязывается к конкретному фреймворку и БД: её нельзя протестировать без них и нельзя переиспользовать в другом месте, а замена фреймворка или БД потребует переписывать бизнес-правила.

**3. Где проверять формат email, а где его уникальность?**
Формат - в транспортном слое: это свойство самих входных данных, и для проверки не нужно ничего знать о системе. У нас это делает Pydantic (`EmailStr` в `UserCreate`). Уникальность - в слое бизнес-логики (`UserService.register`): это правило предметной области («один email - один пользователь»), и для проверки нужны данные системы, которые сервис получает через репозиторий.

**4. Что такое принцип инверсии зависимостей и как он реализован?**
Модули верхнего уровня (бизнес-логика) не должны зависеть от модулей нижнего уровня (БД). Оба должны зависеть от абстракции. У нас `OrderService` зависит от абстрактного `OrderRepository` (ABC), а `PostgresOrderRepository` и `InMemoryOrderRepository` реализуют эту абстракцию. Конкретный объект сервис получает через конструктор, сам его не создаёт: `OrderService(get_order_repository(db))`.

**5. Что изменится при замене PostgreSQL на MongoDB?**
Нужно написать класс `MongoOrderRepository(OrderRepository)` (и аналогичные для users, menu и delivery) и добавить вариант `"mongo"` в фабрики `get_*_repository`. Подключение к Mongo - в отдельном файле вместо `database.py`, модели `models.py` для Mongo не нужны. Изменятся: `repository.py`, `database.py`/новый файл подключения, `config.py`, `main.py` (создание таблиц). Без изменений: все `service.py`, все `router.py`, `schemas.py`, тесты сервисов. Ровно так уже сделана подмена на in-memory хранилище.

**6. Можно ли использовать OrderService в CLI или Celery?**
Да. Сервис не зависит от HTTP и FastAPI: ему нужен только репозиторий. В CLI или задаче Celery достаточно создать сессию БД, собрать `OrderService(PostgresOrderRepository(db))` и вызвать `create_order(...)`. Ошибки придут как обычные исключения Python, и каждое место само решает, что с ними делать: CLI печатает сообщение, Celery пишет в лог. Тесты как раз так и вызывают сервис - без веб-сервера.

**7. Чем техническая валидация отличается от бизнес-валидации?**
Техническая проверяет форму данных, без знания о состоянии системы: тип, формат, диапазон. Примеры: `quantity > 0`, корректный email, длина телефона >= 10, цена > 0. Это делает транспортный слой (Pydantic и роутер). Бизнес-валидация проверяет правила предметной области, обычно с учётом текущих данных: хватает ли денег на балансе, доступно ли блюдо, не заблокирован ли пользователь, уникален ли email, не больше ли пополнение 50000. Это делает сервис.

**8. «service.py импортирует HTTPException для ошибки 400» - что нарушено?**
Нарушено правило зависимостей: внутренний слой (бизнес-логика) зависит от внешнего (веб-фреймворка). Сервис начинает «знать», что его вызывают по HTTP, и его уже не использовать в CLI или Celery без FastAPI, а тесты должны проверять HTTP-коды вместо смысла ошибки. Правильно - бросать доменное исключение (`ValueError`, `NotFoundError`), а в HTTP-код его переводит роутер.

## Другие вопросы, которые могут задать

**Где здесь принцип подстановки Лисков?**
`PostgresOrderRepository` и `InMemoryOrderRepository` взаимозаменяемы: сервис работает с любой из них одинаково и не замечает разницы. Это проверено двумя способами: тесты гоняют настоящие сервисы на in-memory репозиториях, а всё приложение запускается с `REPOSITORY=memory` без единого изменения в `service.py` и `router.py`.

**Зачем ABC, если Python и так работает с любым объектом, у которого есть нужные методы?**
ABC явно описывает контракт, то есть какие методы обязана иметь любая реализация. Если в новой реализации забыть метод, Python не даст создать её объект (`TypeError` при создании), а не упадёт где-то посреди запроса.

**service.py импортирует repository.py, а там есть sqlalchemy. Это не нарушение?**
В самом `service.py` импортов `fastapi` и `sqlalchemy` нет, он импортирует только абстрактный класс для подсказки типа, и этот класс sqlalchemy не использует. По заданию ABC должен лежать в `repository.py`. Если делать строже, интерфейс можно вынести в отдельный файл, и тогда сервис не будет тянуть sqlalchemy даже косвенно.

**В orders деньги списываются и заказ сохраняется двумя отдельными commit. Это проблема?**
Так сделано в методичке. Если после списания упадёт сохранение заказа, деньги спишутся без заказа. В MVP был один commit на всё. Исправить можно так: один метод репозитория, который делает обе операции в одной транзакции, или паттерн Unit of Work, где сервис сам говорит, когда фиксировать транзакцию.

**Почему роутер создаёт сервис сам, а не получает его через Depends?**
Так в шаблоне методички: роутер явно собирает слои, и это видно прямо в коде. Через `Depends` можно сделать так же, просто сборка уедет в отдельную функцию.

**Почему в режиме memory не получается назначить курьера?**
Через API заказ нельзя перевести в `paid`, а SQL-командой в памяти статус не поменяешь. Поэтому `/delivery/assign` в memory-режиме всегда отвечает «только на оплаченный заказ». Ошибки 500 нет, приложение работает, просто данных нужного вида не бывает. Успешные ветки назначения и завершения проверяют unit-тесты: в них оплаченные заказы кладутся прямо в `memory_db`.

**В критерии на 10 баллов про delivery сказано «с асинхронным взаимодействием». Почему у тебя синхронно?**
10 баллов закрывает первый вариант критерия: замена репозитория без изменения `service.py` и `router.py`. `delivery` отрефакторен дополнительно, по той же схеме, что и остальные модули. Асинхронность (async-эндпоинты и асинхронный драйвер БД или фоновая задача на обновление статуса заказа) не делалась.
