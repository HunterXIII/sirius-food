# Лабораторная работа № 3

## Внедрение аутентификации и авторизации в архитектуру Clean Architecture

Дисциплина: Разработка программных модулей и приложений для серверов  
Тема: Безопасность серверных приложений: JWT, RBAC, защита от IDOR  
Продолжительность: 2 академических часа (90 минут) + самостоятельная работа  
Проект: сквозной пет-проект «Сириус.Еда»  
Операционная система: Ubuntu 22.04 LTS или новее

(Условие лабораторной работы № 2 - в коммите с тегом `lab2`: `git show lab2:task.md`.)

### Цели работы

В ходе выполнения лабораторной работы мы:

- Освоим разницу между аутентификацией и авторизацией — научимся разделять эти понятия и применять их на разных слоях архитектуры.
- Внедрим JWT-аутентификацию — реализуем выдачу access- и refresh-токенов, научимся защищать эндпоинты через dependency `get_current_user`.
- Реализуем RBAC (ролевую модель) — разграничим доступ между ролями `student`, `cook`, `courier`, `admin`.
- Закроем уязвимость IDOR — научимся проверять права на конкретный объект в слое бизнес-логики.
- Обеспечим безопасность паролей — реализуем хеширование через bcrypt.

Дополнительно (для 9 баллов):

- Внедрим rate limiting на Redis — защитим эндпоинты от брутфорса и спама.
- Настроим Secure by Default — вынесем секреты в `.env`, ограничим CORS, отключим Swagger в продакшене.

Для 10 баллов — одно задание на выбор:

- Refresh Token rotation — при каждом обновлении access-токена старый refresh-токен инвалидируется, выдаётся новый. Если злоумышленник попытается использовать старый refresh-токен, вся сессия пользователя сбрасывается.
- Защита второго модуля — полностью защитить `users` или `delivery` по образцу `orders`.
- OAuth2 через внешнего провайдера — подключить вход через Google или VK. Документация: https://fastapi.tiangolo.com/advanced/security/oauth2-scopes/.

### Критерии оценивания (10-балльная шкала)

| Баллы | Оценка | Что нужно сделать |
|---|---|---|
| 0–3 | Неудовлетворительно (2) | JWT не внедрён, IDOR не закрыт, проект не запускается. Требования не соблюдены. |
| 4–5 | Удовлетворительно (3) | JWT внедрён, но RBAC или защита от IDOR работают некорректно. Часть эндпоинтов не защищена. Проект запускается, но Swagger не полностью работоспособен. |
| 6–7 | Хорошо (4) | JWT, RBAC и защита от IDOR реализованы корректно. Проект полностью работоспособен в Swagger. `user_id` убран из payload. Хеширование паролей работает. |
| 8 | Отлично (5) | Все требования уровня 6–7 выполнены. Дополнительно: написано не менее 4 тестов на безопасность. Оформлен `README.md`. Устная защита демонстрирует понимание архитектурных решений. |
| 9 | Отлично с плюсом (5+) | Все требования уровня 8 выполнены. Дополнительно: реализован rate limiting на Redis, CORS ограничен, секреты вынесены в `.env`, Swagger отключён в продакшене. |
| 10 | Отлично с двойным плюсом (5++) | Все требования уровня 9 выполнены. Дополнительно выполнено одно задание на выбор: Refresh Token rotation, защита второго модуля или OAuth2-провайдер. |

### 1. Пререквизиты

Для выполнения работы требуется:

- Ubuntu 22.04 LTS (или совместимый дистрибутив Linux);
- Python 3.11 или новее;
- pip и модуль venv;
- Docker Engine и Docker Compose (для PostgreSQL и Redis);
- Git;
- выполненная лабораторная работа № 2 — модули отрефакторены по Clean Architecture.

#### Установка дополнительных зависимостей

Нам нужно установить несколько библиотек. Каждая решает свою задачу:

- `passlib[bcrypt]` — хеширование паролей. Превращает пароль в необратимый хеш, который нельзя восстановить.
- `python-jose[cryptography]` — работа с JWT. Создание и проверка подписи токенов.
- `alembic` — миграции базы данных. Позволяет изменить схему БД без потери данных.
- `redis` — клиент Redis. Понадобится для rate limiting и кеширования.
- `pydantic-settings` — загрузка настроек из `.env`. Позволяет хранить секреты вне кода.

```bash
source .venv/bin/activate
pip install "passlib[bcrypt]" "python-jose[cryptography]" alembic redis pydantic-settings
```

#### Запуск инфраструктуры

PostgreSQL и Redis запускаются в Docker-контейнерах. Это изолирует их от системы и делает конфигурацию воспроизводимой.

```bash
docker compose up -d db redis
```

#### Запуск приложения

```bash
uvicorn app.main:app --reload
```

Проверка: открыть `http://127.0.0.1:8000/docs`. В Swagger должны отображаться эндпоинты всех четырёх модулей.

### 2. Теоретическое введение

#### 2.1. Аутентификация и авторизация

Это два разных процесса, которые часто путают.

Аутентификация отвечает на вопрос «Кто ты?». Это проверка подлинности пользователя: логин и пароль, токен, сертификат.

Авторизация отвечает на вопрос «Что тебе можно?». Это проверка прав: может ли этот пользователь выполнить это действие над этим объектом.

Ошибка на уровне аутентификации приводит к тому, что злоумышленник выдаёт себя за другого пользователя. Ошибка на уровне авторизации приводит к тому, что легальный пользователь получает доступ к чужим данным.

#### 2.2. JWT (JSON Web Token)

JWT — это компактный формат передачи данных, подписанный сервером. Токен состоит из трёх частей, разделённых точками:

```text
header.payload.signature
```

- Header — алгоритм подписи (например, HS256).
- Payload — данные (обычно `sub` — идентификатор пользователя, `exp` — срок действия).
- Signature — подпись, которая проверяется сервером.

Важно: payload не зашифрован, а только закодирован в Base64. Любой может его прочитать. Поэтому в JWT нельзя хранить пароли, персональные данные и другую чувствительную информацию.

- Access-токен — короткоживущий (15 минут). Используется для авторизации запросов.
- Refresh-токен — долгоживущий (7 дней). Используется для получения нового access-токена.

#### 2.3. IDOR (Insecure Direct Object Reference)

IDOR — уязвимость, при которой сервер доверяет идентификатору объекта, пришедшему от клиента, и не проверяет, имеет ли текущий пользователь право на этот объект.

Пример: эндпоинт `POST /orders/{order_id}/cancel` принимает `order_id` и отменяет заказ. Если сервер не проверяет, что заказ принадлежит текущему пользователю, злоумышленник может отменить чужой заказ, подставив другой `order_id`.

Защита: проверка `order.customer_id == current_user.id` в слое бизнес-логики (Service).

#### 2.4. RBAC (Role-Based Access Control)

RBAC — модель управления доступом, при которой права выдаются не конкретному пользователю, а роли. Пользователь получает роль и вместе с ней все её права.

Роли в «Сириус.Еде»: `student`, `cook`, `courier`, `admin`.

Принцип: студент не может видеть кухню, курьер — чужие доставки, повар — создавать заказы.

### 3. Исходное состояние проекта

После выполнения лабораторной работы № 2 модули разделены на три слоя: `router.py`, `service.py`, `repository.py`. Однако система не имеет аутентификации и авторизации. Любой пользователь может:

- отменить чужой заказ (IDOR);
- видеть чужие доставки;
- вызывать эндпоинты, не предназначенные для его роли;
- создавать заказы от имени других пользователей (через `user_id` в payload).

Цель работы — закрыть эти уязвимости, не нарушив архитектуру Clean Architecture.

### 4. Пошаговый разбор внедрения безопасности

#### Шаг 1. Миграция базы данных

Что делаем: добавляем в схему БД таблицы и колонки, необходимые для аутентификации и авторизации.

Зачем: без таблицы `roles` невозможен RBAC. Без `password_hash` нельзя хранить пароли безопасно. Без `refresh_tokens` нельзя реализовать обновление токенов.

##### 1.1. Инициализация Alembic

Alembic — это инструмент миграций. Он позволяет изменять схему БД без потери данных. Инициализация выполняется один раз для проекта.

```bash
alembic init alembic
```

Что произойдёт: создастся папка `alembic/` и файл `alembic.ini`.

Что нужно настроить: в файле `alembic/env.py` укажи `DATABASE_URL` и `Base.metadata`. Это нужно, чтобы Alembic знал, с какой БД работать и какие модели отслеживать. Без этой настройки autogenerate не увидит изменений в моделях.

##### 1.2. Обновить модель User

Что делаем: добавляем в модель поля `password_hash` и `role_id`, создаём модели `Role` и `RefreshToken`.

```python
# app/models.py
from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    """Пользователь системы."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False)
    phone = Column(String, nullable=True)
    balance = Column(Float, default=0.0)
    is_blocked = Column(Boolean, default=False)
    # Хеш пароля. nullable=True на время миграции — заполним позже.
    password_hash = Column(String, nullable=True)
    # Ссылка на роль. nullable=True на время миграции.
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=True)

    role = relationship("Role")


class Role(Base):
    """Роль пользователя: student, cook, courier, admin."""
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)


class RefreshToken(Base):
    """Refresh-токен для обновления access-токена."""
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    # Храним хеш токена, а не сам токен — на случай утечки БД.
    token_hash = Column(String, unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    is_revoked = Column(Boolean, default=False)
```

##### 1.3. Сгенерировать миграцию

Alembic сравнит модели с текущей схемой БД и создаст файл миграции в папке `alembic/versions/`.

```bash
alembic revision --autogenerate -m "add password_hash, roles, refresh_tokens"
```

Что произойдёт: в `alembic/versions/` появится новый файл. Его имя содержит случайный хеш и твоё сообщение, например:

```text
alembic/versions/8f3a2b1c4d5e_add_password_hash_roles_refresh_tokens.py
```

Важно: файл создаётся автоматически. Не создавай его вручную — в нём есть служебные поля (`revision`, `down_revision`), которые связывают миграции в цепочку.

##### 1.4. Отредактировать файл миграции

Что делаем: открываем созданный файл в `alembic/versions/` и дорабатываем функции `upgrade()` и `downgrade()`.

Зачем: Alembic не знает, что нужно заполнить роли или назначить их существующим пользователям. Без этого миграция упадёт на этапе NOT NULL — потому что в БД уже есть пользователи без роли.

Замени содержимое функций на следующий код:

```python
def upgrade():
    # Создаём таблицу ролей.
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(50), unique=True, nullable=False),
    )

    # Добавляем колонки в users. Пока nullable=True — заполним ниже.
    op.add_column("users", sa.Column("password_hash", sa.String(), nullable=True))
    op.add_column("users", sa.Column("role_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_users_role", "users", "roles", ["role_id"], ["id"])

    # Создаём таблицу refresh-токенов.
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("token_hash", sa.String(), unique=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("is_revoked", sa.Boolean(), server_default="false"),
    )

    # Заполняем роли.
    op.execute(
        "INSERT INTO roles (name) VALUES ('student'), ('cook'), ('courier'), ('admin')"
    )
    # Назначаем всем существующим пользователям роль student.
    op.execute(
        "UPDATE users SET role_id = (SELECT id FROM roles WHERE name = 'student')"
    )

    # Теперь можно сделать колонки обязательными.
    op.alter_column("users", "role_id", nullable=False)
    op.alter_column("users", "password_hash", nullable=False)


def downgrade():
    op.drop_table("refresh_tokens")
    op.drop_constraint("fk_users_role", "users", type_="foreignkey")
    op.drop_column("users", "role_id")
    op.drop_column("users", "password_hash")
    op.drop_table("roles")
```

##### 1.5. Применить миграцию

```bash
alembic upgrade head
```

Результат: в БД появились таблицы `roles` и `refresh_tokens`, в `users` добавлены колонки `password_hash` и `role_id`.

#### Шаг 2. Хеширование паролей

Что делаем: реализуем хеширование паролей через bcrypt.

Зачем: хранить пароли в открытом виде нельзя. Если БД утечёт — злоумышленник получит все пароли. Хеш необратим: из него нельзя восстановить исходный пароль, но можно проверить его соответствие.

##### 2.1. Создать модуль app/core/security.py

```python
# app/core/security.py
from passlib.context import CryptContext

# Контекст для хеширования. bcrypt — современный алгоритм с солью.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Возвращает bcrypt-хеш пароля."""
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Проверяет соответствие пароля хешу."""
    return pwd_context.verify(plain, hashed)
```

##### 2.2. Обновить UserService.register()

Что делаем: при регистрации хешируем пароль и назначаем роль `student`.

```python
# app/modules/users/service.py
from app.core.security import hash_password


class UserService:
    def __init__(self, repository: UserRepository):
        self.repository = repository

    def register(self, email: str, password: str, phone: str | None = None) -> User:
        existing = self.repository.get_by_email(email)
        if existing:
            raise EmailAlreadyExistsError()

        user = User(
            email=email,
            phone=phone,
            balance=0.0,
            is_blocked=False,
            password_hash=hash_password(password),
            role_id=self.repository.get_role_id("student"),
        )
        self.repository.save(user)
        return user
```

Результат: пароли в БД хранятся в виде bcrypt-хешей. В открытом виде — нигде.

#### Шаг 3. JWT: логин и выдача токенов

Что делаем: реализуем эндпоинт `POST /auth/login`, который выдаёт пару токенов.

Зачем: клиент предъявляет логин и пароль один раз — и получает токен. Дальше он использует токен для всех запросов. Это безопаснее, чем передавать пароль при каждом запросе.

##### 3.1. Создать модуль app/core/config.py

Что делаем: выносим настройки в отдельный модуль, читаем их из `.env`.

Зачем: секреты не должны быть в коде. `SECRET_KEY` — обязательное поле: приложение не запустится без него. Это принцип Secure by Default.

```python
# app/core/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Настройки приложения, загружаемые из .env."""
    SECRET_KEY: str
    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379"
    DEBUG: bool = False
    ALLOWED_ORIGINS: list[str] = []

    class Config:
        env_file = ".env"


settings = Settings()
```

##### 3.2. Создать файл .env

```text
SECRET_KEY=your-super-secret-key-change-in-production
DATABASE_URL=postgresql://sirius:sirius@localhost:5432/sirius_food
REDIS_URL=redis://localhost:6379
DEBUG=False
ALLOWED_ORIGINS=["https://sirius-food.ru"]
```

Важно: `.env` не должен попадать в Git. Убедись, что он в `.gitignore`.

##### 3.3. Создать модуль app/core/jwt.py

Что делаем: реализуем создание и декодирование токенов.

Зачем: access-токен живёт 15 минут (если украдут — быстро сгорит), refresh-токен — 7 дней (нужен для получения нового access).

```python
# app/core/jwt.py
from datetime import datetime, timedelta
from jose import jwt

from app.core.config import settings

ALGORITHM = "HS256"


def create_access_token(user_id: int) -> str:
    """Создаёт короткоживущий access-токен (15 минут)."""
    payload = {
        "sub": str(user_id),
        "exp": datetime.utcnow() + timedelta(minutes=15),
        "type": "access",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(user_id: int) -> str:
    """Создаёт долгоживущий refresh-токен (7 дней)."""
    payload = {
        "sub": str(user_id),
        "exp": datetime.utcnow() + timedelta(days=7),
        "type": "refresh",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Декодирует и проверяет подпись токена."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
```

##### 3.4. Создать модуль auth с эндпоинтами

Что делаем: создаём отдельный модуль для аутентификации. Он не относится ни к `users`, ни к `orders` — это самостоятельная зона ответственности.

```python
# app/modules/auth/router.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import AuthService

router = APIRouter()


class LoginSchema(BaseModel):
    """Схема запроса на вход."""
    email: EmailStr
    password: str


class RefreshSchema(BaseModel):
    """Схема запроса на обновление токена."""
    refresh_token: str


@router.post("/auth/login")
def login(payload: LoginSchema, db: Session = Depends(get_db)):
    """Аутентификация пользователя и выдача пары токенов."""
    repository = AuthRepository(db)
    service = AuthService(repository)
    return service.login(payload.email, payload.password)
```

##### 3.5. Реализовать AuthService

Что делаем: проверяем email и пароль, выдаём токены.

```python
# app/modules/auth/service.py
from app.core.jwt import create_access_token, create_refresh_token
from app.core.security import verify_password


class InvalidCredentialsError(Exception):
    """Неверный email или пароль."""
    pass


class AuthService:
    def __init__(self, repository: AuthRepository):
        self.repository = repository

    def login(self, email: str, password: str) -> dict:
        """Проверяет учётные данные и возвращает пару токенов."""
        user = self.repository.get_by_email(email)
        if not user or not verify_password(password, user.password_hash):
            raise InvalidCredentialsError()

        access_token = create_access_token(user.id)
        refresh_token = create_refresh_token(user.id)

        # Сохраняем refresh-токен в БД для возможности отзыва.
        self.repository.save_refresh_token(user.id, refresh_token)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
        }
```

Результат: клиент получает пару токенов. Access — для запросов, refresh — для обновления.

#### Шаг 4. get_current_user — защита эндпоинтов

Что делаем: реализуем dependency, которая извлекает пользователя из JWT и защищает эндпоинты.

Зачем: без этой dependency эндпоинты не знают, кто делает запрос. `user_id` из payload — недоверенный источник, его можно подделать. `user_id` из JWT — доверенный, потому что токен подписан сервером.

##### 4.1. Создать app/core/dependencies.py

```python
# app/core/dependencies.py
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.jwt import decode_token
from app.database import get_db
from app.models import User

# Схема извлечения токена из заголовка Authorization.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Извлекает текущего пользователя из JWT.
    Возбуждает HTTPException 401, если токен невалиден.
    """
    try:
        payload = decode_token(token)
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(401, "Invalid token")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(401, "User not found")
    if user.is_blocked:
        raise HTTPException(403, "User is blocked")
    return user
```

##### 4.2. Защитить эндпоинты в orders/router.py

Что делаем: добавляем `Depends(get_current_user)` в эндпоинт создания заказа.

```python
# app/modules/orders/router.py
from app.core.dependencies import get_current_user


@router.post("/create")
def create_order(
    payload: OrderCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    repository = OrderRepository(db)
    service = OrderService(repository)
    order_id = service.create_order(
        user_id=current_user.id,
        item_id=payload.item_id,
        quantity=payload.quantity,
    )
    return {"status": "success", "order_id": order_id}
```

##### 4.3. Убрать user_id из Pydantic-схемы OrderCreate

Что делаем: удаляем `user_id` из схемы. Теперь клиент не сообщает, кто он — это определяет сервер из токена.

```python
# app/schemas.py
class OrderCreate(BaseModel):
    item_id: int
    quantity: int
```

Результат: эндпоинт требует токен. Без токена — 401. `user_id` больше не приходит от клиента.

#### Шаг 5. RBAC: роли и права

Что делаем: реализуем проверку роли через dependency.

Зачем: аутентификация отвечает на вопрос «кто ты». Но она не отвечает на вопрос «что тебе можно». Студент аутентифицирован — но он не должен видеть кухню. Для этого нужна авторизация по ролям.

##### 5.1. Создать require_role

```python
# app/core/dependencies.py
def require_role(required_role: str):
    """
    Dependency для проверки роли пользователя.
    Возбуждает HTTPException 403, если роль не совпадает.
    """
    def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role.name != required_role:
            raise HTTPException(403, "Access denied")
        return current_user
    return checker
```

##### 5.2. Защитить эндпоинты кухни

Что делаем: закрываем эндпоинт `GET /kitchen/orders` ролью `cook`.

```python
# app/modules/orders/router.py
@router.get("/kitchen/orders")
def kitchen_orders(
    current_user: User = Depends(require_role("cook")),
    db: Session = Depends(get_db),
):
    repository = OrderRepository(db)
    service = OrderService(repository)
    return service.get_kitchen_orders()
```

Результат: студент не может видеть кухню — получит 403.

#### Шаг 6. Защита от IDOR в Service-слое

Что делаем: проверяем права на конкретный объект в слое бизнес-логики.

Зачем: это бизнес-правило, а не HTTP-валидация. Оно требует сравнения `order.customer_id` и `current_user.id`. Такая проверка должна быть в Service, а не в роутере — иначе её нельзя протестировать без HTTP и переиспользовать в CLI или воркере.

##### 6.1. Создать доменные исключения

```python
# app/modules/orders/exceptions.py
class OrderNotFoundError(Exception):
    """Заказ не найден."""
    pass


class AccessDeniedError(Exception):
    """Пользователь не имеет прав на этот объект."""
    pass
```

##### 6.2. Обновить OrderService.cancel_order()

```python
# app/modules/orders/service.py
from app.modules.orders.exceptions import AccessDeniedError, OrderNotFoundError


class OrderService:
    def __init__(self, repository: OrderRepository):
        self.repository = repository

    def cancel_order(self, order_id: int, current_user: User) -> Order:
        """
        Отменяет заказ. Проверяет, что заказ принадлежит текущему пользователю.
        Возбуждает OrderNotFoundError или AccessDeniedError.
        """
        order = self.repository.get_order(order_id)
        if order is None:
            raise OrderNotFoundError()
        if order.customer_id != current_user.id:
            raise AccessDeniedError()
        order.cancel()
        self.repository.save(order)
        return order
```

##### 6.3. Транслировать исключения в HTTP-статусы в роутере

```python
# app/modules/orders/router.py
from app.modules.orders.exceptions import AccessDeniedError, OrderNotFoundError


@router.post("/{order_id}/cancel")
def cancel_order(
    order_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    repository = OrderRepository(db)
    service = OrderService(repository)
    try:
        service.cancel_order(order_id, current_user)
    except OrderNotFoundError:
        raise HTTPException(404, "Order not found")
    except AccessDeniedError:
        raise HTTPException(403, "Access denied")
    return {"status": "success"}
```

Результат: IDOR закрыт. Студент А не может отменить заказ студента Б.

#### Шаг 7 (бонус, 9 баллов). Защита API

Что делаем: добавляем rate limiting, ограничиваем CORS, отключаем Swagger в продакшене.

Зачем: эти меры защищают от массовых атак (брутфорс, спам) и снижают поверхность атаки.

##### 7.1. Rate Limiting на Redis

Почему Redis, а не память приложения: если приложение запущено в нескольких репликах, у каждой будет свой счётчик. Пользователь сможет сделать 5 попыток на одной реплике и ещё 5 на другой. Redis хранит общее состояние для всех реплик.

```python
# app/core/rate_limit.py
from fastapi import HTTPException, Request
from redis import Redis

from app.core.config import settings

redis_client = Redis.from_url(settings.REDIS_URL)


def rate_limit(max_requests: int = 5, window: int = 60):
    """
    Dependency для ограничения частоты запросов.
    Возбуждает HTTPException 429 при превышении лимита.
    """
    def checker(request: Request):
        ip = request.client.host
        key = f"rate_limit:{ip}:{request.url.path}"
        current = redis_client.incr(key)
        if current == 1:
            redis_client.expire(key, window)
        if current > max_requests:
            raise HTTPException(429, "Too many requests")
    return checker
```

Применить к эндпоинтам:

```python
@router.post("/auth/login", dependencies=[Depends(rate_limit(5, 60))])
def login(...):
    ...
```

##### 7.2. CORS и отключение Swagger

Что делаем: в продакшене Swagger не нужен — он раскрывает структуру API. CORS ограничиваем только своим доменом.

```python
# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings

app = FastAPI(
    title="Sirius.Food API",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
)
```

Результат: система защищена на уровне конфигурации.

#### Шаг 8 (бонус, 10 баллов). Одно задание на выбор

##### Вариант А. Refresh Token rotation

Что делаем: при каждом обновлении токена старый refresh-токен инвалидируется, выдаётся новый.

Зачем: если злоумышленник украл refresh-токен и попытается его использовать — старая сессия уже недействительна. При повторном использовании старого токена вся сессия сбрасывается.

Что нужно реализовать:

- Эндпоинт `POST /auth/refresh`, который принимает refresh-токен.
- Проверка токена в БД: если он уже `is_revoked` — сбросить всю сессию пользователя.
- Выдача новой пары токенов.
- Инвалидация старого refresh-токена.

##### Вариант Б. Защита второго модуля

Что делаем: полностью защищаем модуль `users` или `delivery` по образцу `orders`.

Что нужно сделать:

- Защитить все эндпоинты через `Depends(get_current_user)`.
- Реализовать проверку прав на объект в Service.
- Добавить роли (`require_role`) там, где это нужно.

##### Вариант В. OAuth2 через внешнего провайдера

Что делаем: подключаем вход через Google или VK.

Зачем: пользователь не хранит пароль в нашей БД — аутентификация делегируется провайдеру.

Что нужно сделать:

- Зарегистрировать приложение в Google Cloud Console или VK ID.
- Реализовать Authorization Code Flow.
- Связать внешний аккаунт с нашим пользователем.

Документация: https://fastapi.tiangolo.com/advanced/security/oauth2-scopes/

### 5. Проверка работоспособности

После внедрения безопасности проект должен сохранять полную работоспособность и одновременно блокировать несанкционированные действия.

Порядок проверки:

- Перезапустить сервер: `uvicorn app.main:app --reload`.
- Открыть `http://127.0.0.1:8000/docs`.
- Сценарий 1: без токена вызвать `POST /orders/create` — получить 401.
- Сценарий 2: залогиниться как студент, получить токен, создать заказ — успех.
- Сценарий 3: залогиниться как второй студент, попытаться отменить заказ первого — получить 403.
- Сценарий 4: залогиниться как студент, вызвать `GET /kitchen/orders` — получить 403.
- Сценарий 5 (бонус): 6 раз подряд вызвать `POST /auth/login` с неверным паролем — на 6-й раз получить 429.

### 6. Задание для самостоятельной работы

Выполнить защиту оставшихся модулей пет-проекта «Сириус.Еда»:

- `users` — регистрация с хешированием пароля, аутентификация, роли.
- `menu` — доступ на изменение только для роли `admin` или `cook`.
- `delivery` — курьер видит только свои доставки; студент не может видеть доставку чужого заказа.

Требования к выполнению:

- Все эндпоинты, изменяющие данные, защищены через `Depends(get_current_user)`.
- Проверка роли реализована через `require_role`.
- Проверка прав на объект реализована в Service-слое.
- Хеширование паролей через bcrypt.
- Проект работает в Swagger, структура ответов не изменилась для авторизованных пользователей.
- Написаны тесты на безопасность (не менее 4):
  - без токена — 401;
  - чужая роль — 403;
  - чужой объект — 403;
  - rate limiting — 429 (бонус).

Задание сдаётся в виде:

- репозитория Git с историей коммитов;
- файла `README.md` с описанием изменений и схемой безопасности;
- тестов на безопасность, проходящих в CI;
- устной защиты с ответами на контрольные вопросы.

### 7. Контрольные вопросы для защиты работы

- Чем аутентификация отличается от авторизации? Приведите пример ошибки на каждом уровне.
- Почему `user_id` убирают из payload запроса и берут из JWT?
- Что такое IDOR и на каком слое архитектуры от него защищаются? Обоснуйте выбор слоя.
- Почему payload JWT нельзя считать защищённым, несмотря на то что он передаётся в токене?
- Почему проверка роли реализована в API-слое, а проверка прав на объект — в Service-слое?
- Зачем нужен rate limiting на Redis, а не в памяти приложения?
- Что такое Secure by Default? Приведите три примера из проекта.
- Какое из следующих утверждений нарушает правило зависимостей Clean Architecture и почему: «`service.py` импортирует `HTTPException` из `fastapi` для возврата ошибки 403»?

## Приложение А. Структура проекта после внедрения безопасности

```text
app/
├── core/
│   ├── config.py         # Pydantic Settings
│   ├── jwt.py            # create_access_token, create_refresh_token, decode_token
│   ├── security.py       # hash_password, verify_password
│   ├── dependencies.py   # get_current_user, require_role
│   └── rate_limit.py     # rate_limit dependency
├── modules/
│   ├── auth/
│   │   ├── router.py
│   │   ├── service.py
│   │   └── repository.py
│   ├── users/
│   │   ├── router.py
│   │   ├── service.py
│   │   └── repository.py
│   ├── menu/
│   │   ├── router.py
│   │   ├── service.py
│   │   └── repository.py
│   ├── orders/
│   │   ├── router.py
│   │   ├── service.py
│   │   ├── repository.py
│   │   └── exceptions.py
│   └── delivery/
│       ├── router.py
│       ├── service.py
│       └── repository.py
├── main.py
├── database.py
├── models.py
└── schemas.py
```

## Приложение Б. Дополнительные зависимости

```text
# requirements.txt
fastapi==0.110.0
uvicorn[standard]==0.29.0
sqlalchemy==2.0.41
psycopg2-binary==2.9.11
pydantic[email]==2.13.0
pydantic-settings==2.2.1
python-dotenv==1.0.1
passlib[bcrypt]==1.7.4
python-jose[cryptography]==3.3.0
alembic==1.13.1
redis==5.0.3
```
