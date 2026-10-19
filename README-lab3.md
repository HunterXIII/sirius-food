# Лабораторная работа 3. Аутентификация и авторизация в Clean Architecture

## Задание

В проекте «Сириус.Еда» после lab2 модули разделены на `router.py`, `service.py`, `repository.py`, но защиты нет: любой может создать заказ от чужого имени (`user_id` в теле запроса), отменить чужой заказ, зайти на кухню и т.д. Нужно:

- хранить пароли как bcrypt-хеши;
- выдавать JWT (access на 15 минут и refresh на 7 дней) через `POST /auth/login`;
- защитить эндпоинты через `get_current_user`, брать `user_id` из токена;
- сделать роли (`student`, `cook`, `courier`, `admin`) и проверку роли `require_role`;
- закрыть IDOR: права на конкретный объект проверять в сервисе;
- на 9 баллов: rate limiting на Redis, CORS, секреты в `.env`, Swagger выключен в продакшене;
- на 10 баллов: одно задание на выбор, у меня Refresh Token rotation.

Полный текст задания lab3 - в коммите с тегом `lab3` (`git show lab3:task.md`), в `task.md` сейчас лежит задание lab4. Задание и README lab2 остались в коммите с тегом `lab2` (`git show lab2:README.md`).

## Что сделано

- Alembic: начальная миграция (таблицы из lab2) и миграция `add password_hash, roles, refresh_tokens` по методичке.
- `app/core/`: настройки из `.env`, bcrypt, JWT, `get_current_user` и `require_role`, rate limiting.
- Модуль `auth`: `POST /auth/login` и `POST /auth/refresh` (rotation).
- `orders` по методичке: `user_id` убран из `OrderCreate`, кухня только для `cook`, отмена заказа с защитой от IDOR.
- Самостоятельная часть, все модули: `users` (пароль, роль student, пополнение только своего баланса, смена роли админом), `menu` (менять могут `admin` и `cook`), `delivery` (назначает админ, видят только курьер доставки и студент, чей заказ, завершить может только свой курьер).
- Шаг 7: rate limiting `/auth/login` на Redis (5 запросов в минуту), CORS, Swagger и `openapi.json` только при `DEBUG=True`, секреты в `.env`.
- Шаг 8, вариант А: Refresh Token rotation с повторным использованием токена = сброс всех сессий.
- 15 HTTP-тестов безопасности (`tests/test_security.py`) и 30 unit-тестов сервисов. CI для GitHub Actions в `.github/workflows/tests.yml`.
- In-memory репозитории из lab2 сохранены и доработаны: тесты и CI работают без PostgreSQL.

## Как запустить

PostgreSQL и Redis:

```bash
docker compose up -d db redis
```

Окружение (проверял на Python 3.12):

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Настройки. `.env` в git не попадает, в репозитории только шаблон:

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
```

Сгенерированную строку вписать в `SECRET_KEY` в `.env`. Без `SECRET_KEY` и `DATABASE_URL` приложение не запустится.

Таблицы. На пустой БД:

```bash
alembic upgrade head
```

Если БД осталась от lab2 (таблицы там создал `create_all`), сначала сказать Alembic, что начальная миграция уже применена, и только потом обновить:

```bash
alembic stamp 945d118d4bed
alembic upgrade head
```

Сервер (при `DEBUG=True` Swagger на http://127.0.0.1:8000/docs):

```bash
uvicorn app.main:app --reload
```

Первый администратор. Регистрация всегда даёт роль `student`, а роли меняет только админ, поэтому первого админа назначаем вручную в БД:

```bash
docker compose exec db psql -U sirius -d sirius_food -c "UPDATE users SET role_id = (SELECT id FROM roles WHERE name = 'admin') WHERE email = 'admin@sirius.ru'"
```

Дальше админ раздаёт роли через `PATCH /users/{user_id}/role` с телом `{"role": "cook"}`.

Как пользоваться Swagger: вызвать `POST /auth/login`, скопировать `access_token` из ответа, нажать Authorize, вставить токен в поле Value. После этого Swagger отправляет заголовок `Authorization: Bearer <токен>` во все запросы.

Тесты (нужен Redis, PostgreSQL не нужен):

```bash
python -m unittest discover tests -v
```

## История коммитов

```text
36321cd Исходный MVP-код проекта Сириус.Еда (Приложение А)
be44b6d Lab2: рефакторинг модулей users, menu, orders, delivery по Clean Architecture   (тег lab2)
d4cd14e Lab3 шаг 1: настройки в .env через pydantic-settings, Alembic и начальная миграция
7d08373 Lab3 шаги 1-2: роли, password_hash и refresh_tokens в БД, хеширование паролей через bcrypt
bf88fc2 Lab3 шаги 3-6: JWT-логин /auth/login, get_current_user, RBAC через require_role, защита orders от IDOR
6c6aac5 Lab3: защита модулей users, menu, delivery (роли и проверка прав на объект в сервисах)
86bd1fb Lab3 шаг 7: rate limiting на Redis для /auth/login, CORS, Swagger только при DEBUG
9e44e98 rate_limit: не падать, если у запроса нет адреса клиента
15a2cd0 Lab3 шаг 8 (вариант А): Refresh Token rotation, POST /auth/refresh
4afb2c5 Тесты безопасности (401, 403 роль, 403 чужой объект, 429, refresh rotation) и CI
d615df4 Lab3: задание (task.md) и README   (тег lab3)
```

## Структура (что добавилось после lab2)

```text
.env.example                 # НОВЫЙ: шаблон настроек (сам .env в .gitignore)
alembic.ini, alembic/        # НОВЫЙ: миграции
  versions/945d118d4bed_initial_tables.py
  versions/a737c7e7ee68_add_password_hash_roles_refresh_tokens.py
.github/workflows/tests.yml  # НОВЫЙ: CI
app/
├── core/                    # НОВЫЙ
│   ├── config.py            # Settings из .env (заменил app/config.py из lab2)
│   ├── security.py          # hash_password, verify_password, hash_token
│   ├── jwt.py               # create_access_token, create_refresh_token, decode_token
│   ├── dependencies.py      # get_current_user, require_role
│   └── rate_limit.py        # rate_limit на Redis
├── modules/
│   ├── auth/                # НОВЫЙ: router, service, repository
│   ├── users/               # пароль и роль при регистрации, IDOR в top_up, смена роли
│   ├── menu/                # require_role("admin", "cook")
│   ├── orders/              # user_id из токена, кухня, отмена с IDOR
│   └── delivery/            # просмотр доставки, IDOR в complete, роль курьера
├── exceptions.py            # + AccessDeniedError
├── memory_db.py             # + роли, пароли, refresh-токены
├── models.py                # + password_hash, role_id, Role, RefreshToken
├── schemas.py               # OrderCreate без user_id, + OrderResponse, DeliveryResponse, RoleUpdate
├── database.py              # DATABASE_URL из настроек, SQL-лог только при DEBUG
└── main.py                  # CORS, Swagger по DEBUG, без create_all
tests/
├── test_services.py         # unit-тесты сервисов (из lab2 + права на объект)
└── test_security.py         # НОВЫЙ: HTTP-тесты 401 / 403 / 429 / rotation
```

## Кто что может

- `POST /auth/login`, `POST /auth/refresh`, `POST /users/register` - без токена. На `/auth/login` не больше 5 запросов в минуту с одного IP.
- `POST /users/{user_id}/topup` - любой вошедший, но только свой баланс (проверка в сервисе).
- `PATCH /users/{user_id}/role` - только `admin`.
- `POST /menu/items`, `PATCH /menu/items/{item_id}` - `admin` или `cook`.
- `POST /orders/create` - только `student`, заказ оформляется на владельца токена.
- `GET /orders/kitchen/orders` - только `cook`.
- `POST /orders/{order_id}/cancel` - любой вошедший, но только свой заказ (в сервисе).
- `POST /delivery/assign` - только `admin`, назначить можно только пользователя с ролью `courier` (в сервисе).
- `GET /delivery/{delivery_id}` - любой вошедший, но видят только курьер этой доставки и студент, чей заказ (в сервисе).
- `PATCH /delivery/{delivery_id}/complete` - только `courier` и только свою доставку (в сервисе).

Ответы всех старых эндпоинтов для авторизованных пользователей не изменились.

## Схема безопасности

Путь запроса, например `POST /orders/5/cancel`:

```text
Клиент
   |  Authorization: Bearer <access_token>
   v
+------------------------------------------------------------------+
| rate_limit (core/rate_limit.py)  - только на /auth/login          |
|   больше 5 запросов за 60 с с одного IP              -> 429       |
+------------------------------------------------------------------+
   v
+------------------------------------------------------------------+
| get_current_user (core/dependencies.py)   АУТЕНТИФИКАЦИЯ: кто ты? |
|   нет заголовка                                      -> 401       |
|   подпись неверна / срок истёк / это refresh-токен   -> 401       |
|   пользователя нет -> 401,  пользователь заблокирован -> 403      |
+------------------------------------------------------------------+
   v
+------------------------------------------------------------------+
| require_role(...) (core/dependencies.py)   АВТОРИЗАЦИЯ ПО РОЛИ    |
|   роль не из списка                                  -> 403       |
+------------------------------------------------------------------+
   v   current_user
+------------------------------------------------------------------+
| router.py   техническая валидация, сборка слоёв,                  |
|             исключения сервиса -> HTTP-коды                       |
+------------------------------------------------------------------+
   v   service.cancel_order(order_id, current_user)
+------------------------------------------------------------------+
| service.py  ПРАВА НА ОБЪЕКТ (IDOR) и бизнес-правила               |
|   заказа нет               -> NotFoundError      -> 404           |
|   order.user_id != current_user.id -> AccessDeniedError -> 403    |
|   заказ уже не processing  -> ValueError         -> 400           |
+------------------------------------------------------------------+
   v
repository.py -> PostgreSQL или memory_db
```

Жизнь токенов:

```text
POST /auth/login {email, password}
   bcrypt: пароль сходится с password_hash?  нет -> 401
   выдаём A1 (access, 15 мин) и R1 (refresh, 7 дней, случайный jti)
   refresh_tokens: + sha256(R1), is_revoked = false

POST /auth/refresh {R1}
   подпись и срок R1 в порядке, type == "refresh", sha256(R1) есть в БД, не отозван
   R1.is_revoked = true, выдаём A2 и R2, сохраняем sha256(R2)

POST /auth/refresh {R1} ещё раз (R1 украли или отправили дважды)
   R1 уже отозван -> отзываем ВСЕ refresh-токены пользователя (R2 тоже) -> 401
   войти можно только заново через /auth/login
```

## Что сделал не так, как в методичке, и почему

1. `HTTPBearer` вместо `OAuth2PasswordBearer`. У `OAuth2PasswordBearer` кнопка Authorize в Swagger просит логин и пароль и отправляет их form-data на `tokenUrl`. А `/auth/login` по методичке принимает JSON (`LoginSchema`), поэтому войти через Swagger было бы нельзя. `HTTPBearer` даёт в Swagger поле, куда вставляется токен. Параметр `auto_error=False` нужен потому, что без заголовка `HTTPBearer` в FastAPI 0.110 отвечает 403, а по заданию нужен 401. Отсутствие токена обрабатываю сам.
2. В `get_current_user` пользователь берётся через `get_user_repository(db)`, а не `db.query(User)`. Так это работает и в memory-режиме из lab2, на нём построены тесты.
3. В `get_current_user` добавил проверку `payload["type"] == "access"`. В методичке её нет, и с refresh-токеном (живёт 7 дней, подписан тем же ключом) можно было бы ходить в API как с access. Есть тест на это.
4. В refresh-токен добавлен `jti` (случайный uuid). Без него два refresh-токена одного пользователя, выданные в одну секунду, получаются одинаковыми (`sub`, `exp` и `type` совпадают), и второй `INSERT` падает на `UNIQUE(token_hash)`. Для rotation это критично: логин и refresh могут случиться в одну секунду.
5. В БД кладётся хеш refresh-токена (SHA-256, `hash_token`), как и сказано в комментарии модели. bcrypt для этого не подходит: токен надо найти в БД по хешу, а bcrypt из-за соли каждый раз даёт новый хеш. Пароли - bcrypt, токены - SHA-256.
6. Миграция методички падала бы на существующих пользователях: роль им назначается, а `password_hash` нет, и `ALTER ... SET NOT NULL` ломается. Я ставлю старым пользователям bcrypt-хеш случайной строки. Её никто не знает, поэтому войти под старыми пользователями нельзя, пока им не зададут пароль.
7. Добавлена начальная миграция с таблицами из lab2, а `Base.metadata.create_all` из `main.py` убран. Иначе на новой пустой БД миграции не на что накатываться. А если оставить `create_all`, он сразу создаст `roles` и `refresh_tokens` из моделей, и `alembic upgrade` упадёт на «таблица уже существует».
8. В модели `password_hash` и `role_id` сразу `nullable=False`, а не `nullable=True` «на время миграции». Модель должна совпадать со схемой после миграции. `alembic check` после `upgrade head` пишет «No new upgrade operations detected».
9. `InvalidCredentialsError` ловится в роутере и превращается в 401. В коде методички она не ловится, и неверный пароль дал бы 500.
10. `AccessDeniedError` положил в общий `app/exceptions.py` из lab2, а не в `orders/exceptions.py`: он нужен в orders, users и delivery. Вместо `OrderNotFoundError` используется `NotFoundError` из lab2.
11. В методичке `order.customer_id`, `order.cancel()`, `repository.get_order/save`. У нас с MVP колонка называется `user_id`, отдельного метода у модели нет, поэтому сервис сам ставит `status = "cancelled"` и сохраняет через `repository.update_order`. Добавил правило: отменить можно только заказ в статусе `processing` (иначе можно было бы «отменить» доставленный).
12. `require_role(*roles)` принимает несколько ролей: меню по заданию могут менять `admin` или `cook`. Вызов `require_role("cook")` работает как в методичке.
13. Создание заказа закрыто `require_role("student")`, а не просто `get_current_user`: в теории сказано, что повар не может создавать заказы.
14. Путь кухни `/orders/kitchen/orders`, а не `/kitchen/orders`: у роутера orders префикс `/orders` (та же ситуация, что в lab2 с `/orders/create`).
15. В `Settings` вместо `class Config` используется `model_config = SettingsConfigDict(...)`. В pydantic 2 `class Config` устарел и даёт предупреждение. Настройка `REPOSITORY` из lab2 переехала туда же, `app/config.py` удалён. Схемы в `schemas.py` тоже переведены на `ConfigDict`.
16. Кроме `docs_url` выключается и `openapi_url`: Swagger только показывает схему API, а сама схема лежит по `/openapi.json` и без этого была бы доступна.
17. `echo=settings.DEBUG` в `database.py`: в lab2 SQL-лог был включён всегда, а в нём видны параметры запросов, то есть хеши паролей и токенов.
18. В `rate_limit` учтено, что `request.client` бывает `None` (стандарт ASGI это допускает, так делает, например, TestClient). Иначе было бы 500.
19. В `requirements.txt` к версиям из Приложения Б добавлены `bcrypt==4.0.1` и `httpx`. passlib 1.7.4 давно не обновлялась: с bcrypt 4.1+ она печатает ошибку чтения версии, а с bcrypt 5 не работает совсем (проверял: `ValueError: password cannot be longer than 72 bytes`). `httpx` нужен для `TestClient`.
20. При регистрации пароль короче 8 символов отклоняется в роутере (400), это техническая валидация.
21. В `assign_courier` проверяется, что назначаемый пользователь - курьер. Иначе админ мог бы назначить студента, и завершить такую доставку (это может только `courier`) было бы некому.

## Разбор кода

### app/core/config.py

Класс `Settings` из `pydantic-settings` читает переменные из `.env` или окружения (окружение главнее). `SECRET_KEY` и `DATABASE_URL` без значения по умолчанию, поэтому без них приложение падает на старте, а не работает с дефолтным секретом. `DEBUG` по умолчанию `False`, `ALLOWED_ORIGINS` по умолчанию пустой. Это Secure by Default: если забыть настройку, получится безопасный вариант. `REPOSITORY` (`postgres` или `memory`) - из lab2.

### app/core/security.py

- `hash_password` / `verify_password` - bcrypt через passlib. В хеше `$2b$12$...` есть соль и число раундов (12), поэтому одинаковые пароли дают разные хеши, а перебор идёт медленно.
- `hash_token` - SHA-256 для refresh-токенов (пункт 5 выше).

### app/core/jwt.py

`create_access_token` (15 минут, `type: access`), `create_refresh_token` (7 дней, `type: refresh`, `jti`), `decode_token` - проверяет подпись и `exp`, при ошибке бросает `JWTError`. Алгоритм HS256: одним `SECRET_KEY` подписываем и проверяем. В `decode` алгоритм задан явно списком, поэтому токен с `"alg": "none"` не пройдёт.

### app/core/dependencies.py

- `get_current_user` - берёт токен из `Authorization: Bearer ...`, декодирует, проверяет тип, достаёт пользователя по `sub` через репозиторий. Ошибки: 401 (нет токена, токен плохой, пользователя нет), 403 (заблокирован).
- `require_role(*roles)` - фабрика зависимостей: возвращает функцию `checker`, которая сама зависит от `get_current_user` и проверяет `current_user.role.name`. Поэтому в роутере достаточно одного `Depends(require_role("cook"))`: и токен, и роль проверятся.

### app/core/rate_limit.py

Ключ `rate_limit:<ip>:<путь>` в Redis. `INCR` увеличивает счётчик (и создаёт ключ, если его нет). На первом запросе ставится `EXPIRE` на 60 секунд, после этого ключ исчезает и счёт начинается заново. Если счётчик больше 5, ответ 429. Считаются все запросы, и успешные тоже.

### Модуль auth

- `repository.py` - `AuthRepository` (ABC) и две реализации, как в lab2: `get_by_email`, `save_refresh_token`, `get_refresh_token`, `revoke_refresh_token`, `revoke_all_user_tokens`.
- `service.py` - `login` (пароль через `verify_password`; одна ошибка и для «нет пользователя», и для «не тот пароль», чтобы по ответу нельзя было проверить, зарегистрирован ли email), `refresh` (rotation, схема выше), `_create_tokens` (создаёт пару и сохраняет хеш refresh). Исключения `InvalidCredentialsError` и `InvalidTokenError`. Импортов `fastapi` и `sqlalchemy` нет.
- `router.py` - `LoginSchema`, `RefreshSchema`, оба эндпоинта. Пути начинаются с `/auth`, поэтому в `main.py` роутер подключён без префикса.

### Миграции (alembic/)

- `env.py` - берёт `DATABASE_URL` из `settings` и `Base.metadata` из моделей (для autogenerate).
- `945d118d4bed_initial_tables` - таблицы lab2, сгенерирована autogenerate на пустой БД.
- `a737c7e7ee68_add_password_hash_roles_refresh_tokens` - сгенерирована autogenerate, тела функций заменены на код методички с исправлением из пункта 6. Порядок: создать `roles`, добавить колонки как nullable, создать `refresh_tokens`, заполнить роли, всем существующим назначить `student` и хеш случайного пароля, потом `SET NOT NULL`. `downgrade` всё откатывает. Внешний ключ создан с именем `fk_users_role`, чтобы его можно было удалить в `downgrade` (autogenerate сделал без имени, и `drop_constraint(None)` не сработал бы).

### orders

- `router.py`: `create_order` берёт `user_id=current_user.id`. Даже если клиент пришлёт `user_id` в теле, Pydantic его просто отбросит, в схеме этого поля нет. `kitchen_orders` с `response_model=list[OrderResponse]`: FastAPI сам превращает ORM-объекты (или записи из памяти) в JSON. `cancel_order` переводит исключения: `NotFoundError` - 404, `AccessDeniedError` - 403, `ValueError` - 400.
- `service.py`: `get_kitchen_orders` (заказы в статусе `processing`), `cancel_order` - сначала «есть ли заказ», потом «твой ли он», потом «можно ли ещё отменить».
- `repository.py`: добавлены `get_order_by_id`, `get_orders_by_status`, `update_order`.

### users

- `register`: пароль хешируется в сервисе, роль `student` берётся через `repository.get_role_id("student")`. Ответ тот же, что в lab2.
- `top_up(user_id, amount, current_user)`: после «пользователь найден» проверка `user.id != current_user.id` и `AccessDeniedError`.
- `change_role`: только для админа (`require_role("admin")` в роутере), в сервисе проверка, что роль существует.

### menu

Сервис не менялся, в роутере на оба эндпоинта `require_role("admin", "cook")`.

### delivery

- `assign_courier` - только админ; в сервисе проверка роли назначаемого курьера.
- `get_delivery` - новый эндпоинт. Сервис пускает только курьера этой доставки (`delivery.courier_id`) и студента, чей заказ (`order.user_id`).
- `complete_delivery` - роль `courier` в роутере, `delivery.courier_id == current_user.id` в сервисе.

### memory_db.py

Добавлены `RoleRecord`, поля `password_hash` и `role_id` у `UserRecord`, `RefreshTokenRecord`. У `UserRecord` есть свойство `role`, которое возвращает роль по `role_id`, как `relationship("Role")` у ORM-модели. Поэтому `current_user.role.name` работает в обоих режимах. Роли заполняются в `clear()` (в PostgreSQL это делает миграция).

### main.py

`FastAPI(docs_url=..., redoc_url=None, openapi_url=...)` - документация только при `DEBUG`. `CORSMiddleware` с `allow_origins=settings.ALLOWED_ORIGINS`, методами GET/POST/PATCH и заголовками Authorization/Content-Type. `create_all` больше нет: таблицы создаёт Alembic.

### Тесты

- `tests/test_services.py` - сервисы с in-memory репозиториями, без HTTP и БД. Добавлены проверки прав на объект прямо в сервисе: чужой заказ, чужой баланс, чужая доставка, другой курьер, назначение не-курьера, смена роли, пароль хранится хешем.
- `tests/test_security.py` - запросы через `TestClient` к настоящему приложению в memory-режиме: 401 (нет токена, мусор вместо токена, refresh вместо access, неверный пароль), 403 по роли (студент на кухне, повар создаёт заказ, студент меняет меню), 403 по объекту (чужой заказ, чужой баланс, чужая доставка), 429, заказ оформляется на владельца токена, rotation. Перед каждым тестом очищаются `memory_db` и счётчики rate limit в Redis. Хеш пароля считается один раз на все тесты, потому что bcrypt медленный.
- CI (`.github/workflows/tests.yml`): Ubuntu, Python 3.12, сервис Redis, настройки через `env` (`.env` в git нет), `python -m unittest discover tests -v`. Удалённого репозитория пока нет, поэтому в GitHub Actions не запускал. Проверил то же самое локально: чистая копия коммита без `.env`, переменные как в workflow, 45 тестов OK.

## Что происходит при запуске

1. `uvicorn` импортирует `app.main`, при этом `app/core/config.py` читает `.env`. Нет `SECRET_KEY` или `DATABASE_URL` - ошибка валидации, сервер не стартует.
2. Создаётся `engine` (подключение к БД будет при первом запросе) и клиент Redis (тоже ленивый).
3. Создаётся `FastAPI`: при `DEBUG=False` без `/docs` и `/openapi.json`. Подключается CORS и роутеры.
4. Пришёл запрос `POST /orders/create` с токеном:
   - FastAPI решает зависимости: `get_db` открывает сессию, `require_role("student")` вызывает `get_current_user`;
   - `get_current_user` проверяет подпись и срок токена, тип `access`, загружает пользователя, проверяет блокировку;
   - `checker` проверяет роль;
   - Pydantic проверяет тело (`item_id`, `quantity`);
   - роутер проверяет `quantity > 0` и вызывает `OrderService.create_order(user_id=current_user.id, ...)`;
   - сервис проверяет блюдо и баланс, через репозиторий списывает деньги и сохраняет заказ;
   - ответ `{"status": "success", "order_id": ...}`, сессия БД закрывается.

## Пример вывода

### Тесты

```text
$ python -m unittest discover tests -v
test_cancel_foreign_order_403 (test_security.SecurityTest.test_cancel_foreign_order_403) ... .venv/lib/python3.12/site-packages/jose/jwt.py:311: DeprecationWarning: datetime.datetime.utcnow() is deprecated ...
ok
test_cook_cannot_create_order_403 (test_security.SecurityTest.test_cook_cannot_create_order_403) ... ok
test_cook_sees_kitchen (test_security.SecurityTest.test_cook_sees_kitchen) ... ok
test_foreign_delivery_403 (test_security.SecurityTest.test_foreign_delivery_403) ... ok
test_invalid_token_401 (test_security.SecurityTest.test_invalid_token_401) ... ok
test_login_rate_limit_429 (test_security.SecurityTest.test_login_rate_limit_429) ... ok
test_no_token_401 (test_security.SecurityTest.test_no_token_401) ... ok
test_order_is_created_for_token_owner (test_security.SecurityTest.test_order_is_created_for_token_owner) ... ok
test_refresh_gives_new_pair (test_security.SecurityTest.test_refresh_gives_new_pair) ... ok
test_refresh_reuse_resets_session (test_security.SecurityTest.test_refresh_reuse_resets_session) ... ok
test_refresh_token_instead_of_access_401 (test_security.SecurityTest.test_refresh_token_instead_of_access_401) ... ok
test_student_cannot_change_menu_403 (test_security.SecurityTest.test_student_cannot_change_menu_403) ... ok
test_student_cannot_see_kitchen_403 (test_security.SecurityTest.test_student_cannot_see_kitchen_403) ... ok
test_topup_foreign_balance_403 (test_security.SecurityTest.test_topup_foreign_balance_403) ... ok
test_wrong_password_401 (test_security.SecurityTest.test_wrong_password_401) ... ok
test_assign_blocked_courier (test_services.DeliveryServiceTest.test_assign_blocked_courier) ... ok
...
test_top_up_over_limit (test_services.UserServiceTest.test_top_up_over_limit) ... ok

----------------------------------------------------------------------
Ran 45 tests in 5.980s

OK
```

`DeprecationWarning` - из самой библиотеки python-jose 3.3.0 (версия из Приложения Б), на работу не влияет.

### Миграция БД, оставшейся от lab2

В БД было 4 пользователя без паролей и ролей:

```text
$ alembic stamp 945d118d4bed
INFO  [alembic.runtime.migration] Running stamp_revision  -> 945d118d4bed
$ alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade 945d118d4bed -> a737c7e7ee68, add password_hash, roles, refresh_tokens

 id |       email       |  role   |  hash
----+-------------------+---------+---------
  1 | client@sirius.ru  | student | $2b$12$
  2 | courier@sirius.ru | student | $2b$12$
  3 | blocked@sirius.ru | student | $2b$12$
  4 | user@example.com  | student | $2b$12$
```

На отдельной пустой БД проверил всю цепочку `upgrade head` -> `downgrade -1` -> `upgrade head` и `alembic check` («No new upgrade operations detected»).

### Сценарии из раздела 5 (PostgreSQL, uvicorn, запросы скриптом)

Формат: `метод путь тело [чей токен] -> ответ [HTTP-код]`, токены обрезаны.

```text
# Подготовка
POST /users/register {"email":"admin@sirius.ru","password":"password123"} -> {"status":"success","user_id":5,"email":"admin@sirius.ru"} [200]
POST /users/register {"email":"ivan@sirius.ru","password":"password123"} -> {"status":"success","user_id":6,"email":"ivan@sirius.ru"} [200]
POST /users/register {"email":"petr@sirius.ru","password":"password123"} -> {"status":"success","user_id":7,"email":"petr@sirius.ru"} [200]
POST /users/register {"email":"povar@sirius.ru","password":"password123"} -> {"status":"success","user_id":8,"email":"povar@sirius.ru"} [200]
POST /users/register {"email":"kurier@sirius.ru","password":"password123"} -> {"status":"success","user_id":9,"email":"kurier@sirius.ru"} [200]
(SQL) UPDATE users SET role_id = <admin> WHERE email = 'admin@sirius.ru'
POST /auth/login {"email":"admin@sirius.ru","password":"password123"} -> {"access_token":"eyJhbGciOiJIUzI1...","refresh_token":"eyJhbGciOiJIUzI1...","token_type":"bearer"} [200]
PATCH /users/8/role {"role":"cook"} [admin] -> {"status":"success","user_id":8,"role":"cook"} [200]
PATCH /users/9/role {"role":"courier"} [admin] -> {"status":"success","user_id":9,"role":"courier"} [200]
POST /auth/login {"email":"ivan@sirius.ru","password":"password123"} -> {"access_token":"eyJhbGciOiJIUzI1...","refresh_token":"eyJhbGciOiJIUzI1...","token_type":"bearer"} [200]
POST /auth/login {"email":"petr@sirius.ru","password":"password123"} -> {...} [200]
POST /auth/login {"email":"povar@sirius.ru","password":"password123"} -> {...} [200]
POST /menu/items {"name":"Плов","price":230} [povar] -> {"status":"success","item_id":3} [200]
POST /users/6/topup?amount=1000 [ivan] -> {"status":"success","new_balance":1000.0} [200]

# Сценарий 1: без токена
POST /orders/create {"item_id":3,"quantity":1} -> {"detail":"Not authenticated"} [401]

# Сценарий 2: студент создаёт заказ
POST /orders/create {"item_id":3,"quantity":2} [ivan] -> {"status":"success","order_id":5} [200]

# Сценарий 3: второй студент отменяет заказ первого
POST /orders/5/cancel [petr] -> {"detail":"Нельзя отменить чужой заказ"} [403]

# Сценарий 4: студент вызывает кухню (и повар для сравнения)
GET /orders/kitchen/orders [ivan] -> {"detail":"Access denied"} [403]
GET /orders/kitchen/orders [povar] -> [{"id":3,"user_id":1,"item_id":1,"quantity":1,"status":"processing"},{"id":4,"user_id":4,"item_id":2,"quantity":2,"status":"processing"},{"id":5,"user_id":6,"item_id":3,"quantity":2,"status":"processing"}] [200]

# Остальное: чужой баланс, меню студентом, повар делает заказ, старый пользователь из lab2
POST /users/6/topup?amount=100 [petr] -> {"detail":"Нельзя пополнить чужой баланс"} [403]
POST /menu/items {"name":"Компот","price":50} [ivan] -> {"detail":"Access denied"} [403]
POST /orders/create {"item_id":3,"quantity":1} [povar] -> {"detail":"Access denied"} [403]
POST /auth/login {"email":"client@sirius.ru","password":"anything"} -> {"detail":"Invalid email or password"} [401]

# Refresh Token rotation (R1 - refresh из логина ivan, R2 - из ответа на первый refresh)
POST /auth/refresh {"refresh_token":"<R1>"} -> {"access_token":"eyJhbGciOiJIUzI1...","refresh_token":"eyJhbGciOiJIUzI1...","token_type":"bearer"} [200]
POST /auth/refresh {"refresh_token":"<R1>"} -> {"detail":"Invalid refresh token"} [401]
POST /auth/refresh {"refresh_token":"<R2>"} -> {"detail":"Invalid refresh token"} [401]
```

Последняя строка: R2 ещё ни разу не использовали, но после повторного R1 сессия сброшена целиком.

Сценарий 5 пришлось запускать отдельно. В общем скрипте до него уже было 5 входов за минуту с того же IP, и сразу пришёл 429: лимит считает все попытки входа с IP, не только неверные. Отдельно, на чистом счётчике:

```text
POST /auth/login {"email":"ivan@sirius.ru","password":"wrong-pass"} -> {"detail":"Invalid email or password"} [401]
POST /auth/login {"email":"ivan@sirius.ru","password":"wrong-pass"} -> {"detail":"Invalid email or password"} [401]
POST /auth/login {"email":"ivan@sirius.ru","password":"wrong-pass"} -> {"detail":"Invalid email or password"} [401]
POST /auth/login {"email":"ivan@sirius.ru","password":"wrong-pass"} -> {"detail":"Invalid email or password"} [401]
POST /auth/login {"email":"ivan@sirius.ru","password":"wrong-pass"} -> {"detail":"Invalid email or password"} [401]
POST /auth/login {"email":"ivan@sirius.ru","password":"wrong-pass"} -> {"detail":"Too many requests"} [429]

$ redis-cli get rate_limit:127.0.0.1:/auth/login   ->  6
$ redis-cli ttl rate_limit:127.0.0.1:/auth/login   ->  58
```

### Что лежит в БД после сценариев

```text
 id |      email       |          password_hash
----+------------------+----------------------------------
  5 | admin@sirius.ru  | $2b$12$C4mFJl8Kdx7uYlVIMrf6PO...
  6 | ivan@sirius.ru   | $2b$12$2MOM77ZlZZOiN2X5mxQEBO...
  ...

 id | user_id |     token_hash      |         expires_at         | is_revoked
----+---------+---------------------+----------------------------+------------
  1 |       5 | 696b837623527314... | 2026-10-24 13:03:30.264135 | f
  2 |       6 | 9a7ec21651da3a09... | 2026-10-24 13:03:30.479553 | t
  3 |       7 | cc443c398522d50d... | 2026-10-24 13:03:30.681206 | f
  4 |       8 | e1a6233b3ede8c07... | 2026-10-24 13:03:30.881304 | f
  5 |       6 | a1e6d5d8c2dc112a... | 2026-10-24 13:03:31.13138  | t
```

Паролей в открытом виде нет, токенов тоже, только хеши. У ivan (user_id 6) отозваны оба токена: R1 отозван при обмене, R2 при сбросе сессии. `expires_at` в UTC, через 7 дней.

SQL-лог rotation (сервер с `DEBUG=True`): обычный refresh отзывает один токен, повторный - все токены пользователя.

```text
INFO sqlalchemy.engine.Engine UPDATE refresh_tokens SET is_revoked=%(is_revoked)s WHERE refresh_tokens.id = %(refresh_tokens_id)s
INFO sqlalchemy.engine.Engine [generated in 0.00012s] {'is_revoked': True, 'refresh_tokens_id': 6}
INFO sqlalchemy.engine.Engine INSERT INTO refresh_tokens (user_id, token_hash, expires_at, is_revoked) VALUES (...) RETURNING refresh_tokens.id
INFO:     127.0.0.1:60894 - "POST /auth/refresh HTTP/1.1" 200 OK
INFO sqlalchemy.engine.Engine UPDATE refresh_tokens SET is_revoked=%(is_revoked)s WHERE refresh_tokens.user_id = %(user_id_1)s
INFO:     127.0.0.1:60898 - "POST /auth/refresh HTTP/1.1" 401 Unauthorized
```

### Swagger и CORS

```text
DEBUG=True  /docs 200 /openapi.json 200
DEBUG=False /docs 404 /openapi.json 404

OPTIONS /auth/login  Origin: http://localhost:3000   -> 200, access-control-allow-origin: http://localhost:3000
OPTIONS /auth/login  Origin: https://evil.example    -> 400, заголовка access-control-allow-origin нет
```

Схема безопасности в `openapi.json`: `{'HTTPBearer': {'type': 'http', 'scheme': 'bearer'}}`. Без замка (без токена) только `/auth/login`, `/auth/refresh` и `/users/register`, у остальных 10 эндпоинтов замок.

## Ответы на контрольные вопросы

**1. Чем аутентификация отличается от авторизации? Пример ошибки на каждом уровне.**
Аутентификация - «кто ты»: проверка пароля в `AuthService.login` и проверка подписи токена в `get_current_user`. Авторизация - «что тебе можно»: `require_role` и проверки владельца в сервисах. Ошибка аутентификации: сервер принимает токен без проверки подписи или со слабым `SECRET_KEY`, и злоумышленник подделывает токен с чужим `sub`, то есть выдаёт себя за другого. Ошибка авторизации: пользователь вошёл честно, но `cancel_order` не сравнивает `order.user_id` с `current_user.id`, и он отменяет чужой заказ (IDOR).

**2. Почему `user_id` убирают из payload и берут из JWT?**
Тело запроса клиент пишет сам, туда можно поставить любой `user_id` и заказать за чужой счёт. JWT подписан сервером секретным ключом: если поменять `sub`, подпись не сойдётся, и `decode_token` бросит ошибку. Поэтому `user_id` из токена - доверенный. Тест `test_order_is_created_for_token_owner` отправляет `"user_id": 2` с токеном пользователя 1, и заказ всё равно оформляется на 1.

**3. Что такое IDOR и на каком слое от него защищаются?**
IDOR - сервер берёт id объекта от клиента (`/orders/5/cancel`) и не проверяет, имеет ли текущий пользователь право на этот объект. Защита - в Service: проверка «заказ принадлежит пользователю» - это бизнес-правило предметной области, а не свойство HTTP-запроса. Для проверки нужен сам объект из хранилища, а его получает сервис. В сервисе правило работает при любом способе вызова (HTTP, CLI, воркер) и тестируется без HTTP (`test_cancel_foreign_order` в `test_services.py`). В роутере его пришлось бы повторять в каждом входе.

**4. Почему payload JWT нельзя считать защищённым?**
Он только закодирован в Base64url, а не зашифрован. Подпись защищает от изменения, но не от чтения. Пример - payload нашего refresh-токена, декодированный обычным `base64 -d`:

```text
{"sub":"6","exp":1792847010,"type":"refresh","jti":"f30fda29-5533-424e-a8bf-beea749363de"}
```

Поэтому в токене только id пользователя, срок, тип и jti. Ни пароля, ни email, ни баланса.

**5. Почему проверка роли в API-слое, а проверка прав на объект - в Service?**
Для роли нужен только текущий пользователь, и это правило доступа к эндпоинту целиком: «на кухню - только повар». Его удобно навесить декларативно через `Depends(require_role("cook"))`, и до сервиса запрос даже не дойдёт. Для прав на объект нужно загрузить сам объект и сравнить его поля с пользователем (`order.user_id`, `delivery.courier_id`). Это бизнес-логика, и данные для неё есть только в сервисе. К тому же правило должно действовать при любом способе вызова сервиса.

**6. Зачем rate limiting на Redis, а не в памяти приложения?**
Если приложение запущено в нескольких репликах (или uvicorn с несколькими воркерами), у каждой свой счётчик в памяти: 5 попыток на одной реплике, 5 на другой, и лимит фактически умножается на число реплик. Счётчик в памяти ещё и обнуляется при перезапуске. Redis - один общий счётчик для всех, а `EXPIRE` сам удаляет ключ по истечении окна.

**7. Что такое Secure by Default? Три примера из проекта.**
По умолчанию система в безопасном состоянии, а ослабить защиту можно только явно. Примеры:
- `SECRET_KEY` без значения по умолчанию: без него приложение не стартует, а не работает с известным всем ключом;
- `DEBUG=False` по умолчанию: Swagger, `openapi.json` и SQL-лог выключены, пока их явно не включили;
- `ALLOWED_ORIGINS=[]` по умолчанию: CORS не пускает ни один чужой домен;
- новый пользователь всегда получает самую слабую роль `student`, повышает только админ;
- защищённые эндпоинты требуют токен, а `get_current_user` пропускает только `access`-токены.

**8. «service.py импортирует HTTPException для ошибки 403» - что нарушено?**
Правило зависимостей: внутренний слой (бизнес-логика) начинает зависеть от внешнего (веб-фреймворка). Сервис «знает», что его вызывают по HTTP, и в CLI или Celery без FastAPI его не использовать, а тесты проверяли бы HTTP-коды вместо смысла ошибки. Правильно так, как сделано: сервис бросает `AccessDeniedError`, а роутер переводит её в 403.

## Другие вопросы, которые могут задать

**Чем 401 отличается от 403?**
401 - «не знаю, кто ты»: нет токена или он невалиден, надо войти. 403 - «знаю, кто ты, но нельзя»: роль не подходит, объект чужой, пользователь заблокирован.

**Почему после сброса сессии access-токен ещё работает?**
Access-токен проверяется только по подписи и сроку, в БД за ним не ходим (stateless). Поэтому после отзыва refresh-токенов украденный access проживёт до 15 минут. Поэтому он и короткий. Если нужно отзывать сразу, придётся хранить в Redis чёрный список `jti` access-токенов и проверять его в `get_current_user`.

**Почему лимит по IP, а не по email?**
Так в методичке. Лимит по IP защищает и от перебора паролей одного пользователя, и от перебора разных email. Минус: студенты за одним NAT (общежитие, одна сеть) делят лимит, и успешные входы тоже считаются. Лимит только по email позволил бы злоумышленнику заблокировать вход конкретному человеку, просто вводя его email с неверным паролем.

**Что будет, если утечёт `SECRET_KEY`?**
Можно подписать токен с любым `sub` и войти под кем угодно, в том числе под админом. Нужно сменить ключ: все выданные токены сразу станут недействительными, всем придётся войти заново.

**Почему старые пользователи из lab2 не могут войти?**
Паролей у них не было. Миграция поставила им хеш случайной строки, которую никто не знает (иначе `NOT NULL` не применить). Ставить всем общий известный пароль вроде `changeme` небезопасно. Ответ при входе тот же, что при неверном пароле: 401.

**Возвращаются ли деньги при отмене заказа?**
Нет, ни в методичке, ни в задании этого нет. В заказе не хранится сумма, а цена блюда могла поменяться, поэтому для возврата пришлось бы добавить в `orders` колонку с суммой (ещё одна миграция).

**Почему для чужого заказа 403, а не 404?**
Так в методичке, и так проще отлаживать. Строже было бы отвечать 404 и на «нет такого заказа», и на «заказ чужой»: тогда перебором id нельзя узнать, какие заказы существуют.

**Как сделать админа в memory-режиме?**
Через API никак, SQL-команды тоже нет. В тестах пользователи с нужными ролями кладутся прямо в `memory_db`. Memory-режим нужен для тестов и CI, а не для ручной работы.

**Сервис delivery проверяет `courier.role.name`. Это не проверка роли в сервисе?**
Это не проверка прав того, кто делает запрос (это `require_role("admin")` в роутере). Это бизнес-правило про данные: на доставку можно назначить только курьера. Оно про назначаемого пользователя, поэтому место ему в сервисе.

**Почему тесты безопасности в memory-режиме, а не на PostgreSQL?**
Чтобы они шли в CI без базы, быстро и на чистых данных. Логика безопасности (`get_current_user`, `require_role`, сервисы) одинаковая в обоих режимах, отличается только репозиторий. На PostgreSQL те же сценарии прогнаны вручную, вывод выше.
