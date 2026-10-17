# Лабораторная работа № 2

## Рефакторинг MVP-модулей в архитектуру Clean Architecture

Дисциплина: Разработка программных модулей и приложений для серверов  
Тема: Применение принципов Чистой архитектуры (Clean Architecture)  
Продолжительность: 2 академических часа (90 минут)  
Проект: сквозной пет-проект «Сириус.Еда»  
Операционная система: Ubuntu 22.04 LTS или новее

### 1. Пререквизиты

Для выполнения работы требуется:

- Ubuntu 22.04 LTS (или совместимый дистрибутив Linux);
- Python 3.11 или новее;
- менеджер пакетов `pip` и модуль `venv`;
- Docker Engine и Docker Compose (для запуска PostgreSQL и Redis);
- Git.

Установка зависимостей в терминале:

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv docker.io docker-compose git

python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn sqlalchemy psycopg2-binary pydantic python-dotenv
```

Запуск инфраструктуры:

```bash
sudo docker-compose up -d db redis
```

Запуск приложения:

```bash
uvicorn app.main:app --reload
```

Проверка: открыть в браузере `http://127.0.0.1:8000/docs`. В интерфейсе Swagger должны отображаться эндпоинты всех четырёх модулей.

### 2. Теоретическое введение

#### 2.1. Проблема жёсткой связности (Tight Coupling)

На этапе разработки минимально жизнеспособного продукта (MVP) код часто пишется без разделения на слои: обработка HTTP-запроса, бизнес-проверки и SQL-запросы размещаются в одной функции-обработчике. Такой подход сокращает время разработки на старте, однако приводит к следующим недостаткам:

- низкая поддерживаемость: изменение схемы базы данных или замена веб-фреймворка требует переписывания значительной части кода;
- невозможность изолированного тестирования: для проверки бизнес-правила требуется запуск СУБД и веб-сервера;
- дублирование логики: одно и то же бизнес-правило может быть реализовано в нескольких эндпоинтах с небольшими расхождениями.

#### 2.2. Концепция Clean Architecture

Концепция предложена Робертом Мартином в 2012 году. Фундаментальный принцип: направление зависимостей строго ориентировано снаружи внутрь. Внутренние слои не должны знать о существовании внешних.

Эталонная модель содержит четыре концентрических круга (изнутри наружу):

- Entities — бизнес-сущности предметной области.
- Use Cases — сценарии использования (прикладная логика).
- Interface Adapters — адаптеры интерфейсов (репозитории, презентеры, контроллеры).
- Frameworks & Drivers — фреймворки, драйверы, СУБД.

При проектировании веб-сервисов четыре круга принято группировать в три практических слоя:

| Слой в проекте | Файл | Соответствие модели Мартина | Зона ответственности |
|---|---|---|---|
| API Layer (транспортный) | `router.py` | Круг 4: Frameworks & Drivers | Приём HTTP-запроса, техническая валидация (Pydantic), трансляция исключений в HTTP-статусы, возврат ответа |
| Business Logic Layer | `service.py` | Круги 1 и 2: Entities и Use Cases | Бизнес-правила предметной области, оркестрация сценария |
| Infrastructure Layer | `repository.py` | Круг 3: Interface Adapters | SQL-запросы, транзакции, взаимодействие с СУБД через ORM |

Ключевое ограничение: в файле `service.py` запрещены импорты `fastapi` и `sqlalchemy`. Это архитектурное требование, а не стилистическая рекомендация.

#### 2.3. Паттерн Repository

Repository — это архитектурный паттерн, инкапсулирующий логику доступа к данным. Бизнес-логика обращается к репозиторию через методы, семантика которых отражает предметную область (`save_order`, `get_user_by_id`), а не технические операции (`INSERT`, `SELECT`). Реализация репозитория может быть заменена без изменения бизнес-логики: PostgreSQL, MongoDB, in-memory-хранилище.

### 3. Исходное состояние проекта

Проект «Сириус.Еда» представляет собой модульный монолит, состоящий из четырёх модулей: `users`, `menu`, `orders`, `delivery`. Все модули написаны в MVP-стиле: бизнес-логика, SQL-запросы и обработка HTTP находятся в одном файле.

В рамках лабораторной работы выполняется рефакторинг одного модуля совместно с преподавателем (`orders`) и одного модуля самостоятельно (по указанию преподавателя: `users` или `menu`).

Полный исходный код всех модулей приведён в Приложении А.

### 4. Пошаговый разбор рефакторинга модуля `orders`

#### Шаг 1. Изоляция инфраструктурного слоя (`repository.py`)

Создать файл `orders/repository.py`. В него переносится весь код, содержащий прямые импорты `sqlalchemy` и знание внутренней структуры моделей базы данных. Взаимодействие организуется через класс `OrderRepository`.

```python
# orders/repository.py
from sqlalchemy.orm import Session
from models import Order, User, MenuItem


class OrderRepository:
    """
    Класс отвечает исключительно за выполнение операций ввода-вывода
    в контексте СУБД PostgreSQL с использованием SQLAlchemy ORM.
    Бизнес-правила в данном классе отсутствуют.
    """

    def __init__(self, db: Session):
        self.db = db

    def get_user_by_id(self, user_id: int):
        """Извлечение объекта пользователя по идентификатору."""
        return self.db.query(User).filter(User.id == user_id).first()

    def get_menu_item_by_id(self, item_id: int):
        """Извлечение объекта блюда из меню по идентификатору."""
        return self.db.query(MenuItem).filter(MenuItem.id == item_id).first()

    def save_order(self, user_id: int, item_id: int, quantity: int) -> int:
        """
        Создание новой записи заказа и фиксация транзакции.
        Возвращает идентификатор созданного заказа.
        """
        new_order = Order(
            user_id=user_id,
            item_id=item_id,
            quantity=quantity,
            status="processing",
        )
        self.db.add(new_order)
        self.db.commit()
        self.db.refresh(new_order)
        return new_order.id

    def update_user_balance(self, user, new_balance: float) -> None:
        """Изменение значения баланса пользователя с фиксацией транзакции."""
        user.balance = new_balance
        self.db.add(user)
        self.db.commit()
```

После выполнения шага единственным компонентом, знающим о структуре SQL-таблиц, становится данный файл.

#### Шаг 2. Реализация слоя бизнес-логики (`service.py`)

Создать файл `orders/service.py`. Данный слой не должен зависеть от веб-интерфейса и механизмов хранения данных. Применение импортов из `fastapi` или `sqlalchemy` в этом файле является архитектурной ошибкой.

Связывание со слоем данных выполняется через принцип инверсии зависимостей: экземпляр репозитория передаётся в конструктор сервиса как абстрактная зависимость.

```python
# orders/service.py
from orders.repository import OrderRepository


class OrderService:
    """
    Класс инкапсулирует бизнес-правила обработки заказов.
    Не имеет зависимостей от инфраструктурных фреймворков.
    """

    def __init__(self, repository: OrderRepository):
        # Внедрение зависимости через конструктор.
        self.repository = repository

    def create_order(self, user_id: int, item_id: int, quantity: int) -> int:
        """
        Исполнение сценария оформления заказа.
        Возвращает идентификатор созданного заказа.
        Возбуждает ValueError при нарушении бизнес-правил.
        """
        user = self.repository.get_user_by_id(user_id)
        if not user:
            raise ValueError("Пользователь не найден")

        item = self.repository.get_menu_item_by_id(item_id)
        if not item:
            raise ValueError("Указанное блюдо не найдено в меню")

        if not item.is_available:
            raise ValueError("Блюдо временно недоступно")

        total_cost = item.price * quantity
        if user.balance < total_cost:
            raise ValueError("Недостаточно средств на балансе студента")

        # Изменение состояния доменных данных.
        user.balance -= total_cost
        self.repository.update_user_balance(user, user.balance)

        # Делегирование операции сохранения инфраструктурному слою.
        order_id = self.repository.save_order(user_id, item_id, quantity)
        return order_id
```

#### Шаг 3. Очистка транспортного слоя (`router.py`)

Исходный файл `orders/router.py` модифицируется: из него удаляются прямые обращения к моделям данных и бизнес-проверки. Роутер выполняет роль диспетчера: собирает слои, передаёт параметры в сервис и транслирует исключения языка Python в HTTP-статусы.

```python
# orders/router.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from schemas import OrderCreate
from orders.repository import OrderRepository
from orders.service import OrderService

router = APIRouter()


@router.post("/orders/create")
def create_order(payload: OrderCreate, db: Session = Depends(get_db)):
    # Техническая валидация уровня транспортного протокола.
    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="Количество должно быть больше нуля")

    # Сборка архитектурных слоёв.
    repository = OrderRepository(db)
    service = OrderService(repository)

    # Делегирование выполнения сценария слою бизнес-логики.
    try:
        order_id = service.create_order(
            user_id=payload.user_id,
            item_id=payload.item_id,
            quantity=payload.quantity,
        )
    except ValueError as e:
        # Трансляция внутреннего исключения в HTTP-статус.
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "success", "order_id": order_id}
```

### 5. Проверка работоспособности

После выполнения рефакторинга проект должен сохранять полную работоспособность. Изменение внутренней архитектуры не должно изменять внешнее поведение API.

Порядок проверки:

- Перезапустить сервер: `uvicorn app.main:app --reload`.
- Открыть `http://127.0.0.1:8000/docs`.
- Выполнить запрос `POST /orders/create` с тестовыми данными.
- Убедиться, что заказ создан, баланс пользователя списан, структура ответа идентична структуре ответа до рефакторинга.
- Проверить, что в терминале отображаются SQL-логи, соответствующие операциям `INSERT` и `UPDATE`.

### 6. Задание для самостоятельной работы

В аналогичном MVP-состоянии находятся модули `users` и `menu`. Модуль `delivery` может быть выбран дополнительно студентами, претендующими на повышенную оценку.

Задание: выполнить рефакторинг указанного преподавателем модуля в соответствии с принципами Clean Architecture, используя разобранный шаблон модуля `orders`.

Требования к выполнению:

- Разделить модуль на три файла: `router.py`, `service.py`, `repository.py`.
- В файле `service.py` обеспечить отсутствие импортов `fastapi` и `sqlalchemy`.
- Реализовать передачу репозитория в сервис через конструктор (инверсия зависимостей).
- Сохранить работоспособность приложения: при запуске сервера эндпоинты рефакторируемого модуля в Swagger должны корректно принимать и обрабатывать запросы, возвращая идентичные структуры ответов.
- Добавить не менее одного unit-теста на `service.py`, не требующего запуска СУБД.

Задание сдаётся в виде:

- репозитория Git с историей коммитов, отражающей процесс рефакторинга;
- файла `README.md` с описанием изменений и диаграммой пути запроса через слои;
- устной защиты с ответами на контрольные вопросы.

### 7. Критерии оценивания (10-балльная шкала)

| Баллы | Оценка по 5-балльной шкале | Критерии |
|---|---|---|
| 0–3 | Неудовлетворительно (2) | Рефакторинг не выполнен или выполнен формально. Импорты `fastapi` и `sqlalchemy` присутствуют в `service.py`. Проект не запускается. Требования не соблюдены. |
| 4–5 | Удовлетворительно (3) | Модуль разделён на три файла, однако границы слоёв нарушены: в `service.py` присутствуют обращения к моделям БД или к `HTTPException`. Инверсия зависимостей не реализована либо реализована с ошибками. Проект запускается, но часть эндпоинтов работает некорректно. |
| 6–7 | Хорошо (4) | Модуль разделён на три слоя корректно. `service.py` не импортирует `fastapi` и `sqlalchemy`. Инверсия зависимостей реализована через конструктор. Проект полностью работоспособен в Swagger, ответы идентичны исходным. Unit-тесты отсутствуют. |
| 8 | Отлично (5) | Все требования уровня 6–7 выполнены. Дополнительно: написан минимум один unit-тест на `service.py`, не требующий запуска СУБД. Оформлен `README.md` с описанием изменений и схемой слоёв. Устная защита демонстрирует понимание архитектурных решений. |
| 9 | Отлично с плюсом (5+) | Все требования уровня 8 выполнены. Дополнительно: отрефакторены два модуля вместо одного, либо в `repository.py` выделен абстрактный интерфейс (ABC) с двумя реализациями (например, PostgreSQL и in-memory для тестов). |
| 10 | Отлично с двойным плюсом (5++) | Все требования уровня 9 выполнены. Дополнительно: реализована полноценная замена реализации репозитория без изменения `service.py` и `router.py` (принцип подстановки Лисков), либо выполнен рефакторинг модуля `delivery`, включающего асинхронное взаимодействие. |

### 8. Контрольные вопросы для защиты работы

- Какому кругу эталонной модели Роберта Мартина соответствует компонент `repository.py`? Обоснуйте ответ.
- Почему в файле `service.py` запрещено использовать импорты модулей `fastapi` и `sqlalchemy`? Какое архитектурное правило при этом соблюдается?
- В каком слое должна выполняться проверка формата входящего email-адреса, а в каком — проверка уникальности этого email среди существующих пользователей? Объясните с точки зрения разделения ответственности слоёв.
- Что представляет собой принцип инверсии зависимостей (Dependency Inversion Principle) и как он реализован в разобранном решении?
- Какие изменения потребуется внести в проект при замене PostgreSQL на MongoDB? Какие файлы будут затронуты, а какие останутся без изменений?
- Возможно ли повторное использование класса `OrderService` в CLI-утилите или в фоновом обработчике задач (например, Celery)? Обоснуйте ответ.
- В чём разница между технической валидацией входных данных и бизнес-валидацией предметной области? Приведите примеры для каждого типа.
- Какое из следующих утверждений нарушает правило зависимостей Clean Architecture и почему: «`service.py` импортирует `HTTPException` из `fastapi` для возврата ошибки 400»?

## Приложение А. Исходный код MVP-версии проекта

### A.1. Структура проекта

```text
sirius_food/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── database.py
│   ├── models.py
│   ├── schemas.py
│   └── modules/
│       ├── users/
│       │   └── router.py
│       ├── menu/
│       │   └── router.py
│       ├── orders/
│       │   └── router.py
│       └── delivery/
│           └── router.py
├── docker-compose.yml
└── requirements.txt
```

### A.2. `app/main.py`

```python
"""
Точка входа приложения. Выполняет инициализацию FastAPI,
подключение модулей и создание таблиц базы данных.
"""
from fastapi import FastAPI
from app.database import Base, engine
from app.modules.users.router import router as users_router
from app.modules.menu.router import router as menu_router
from app.modules.orders.router import router as orders_router
from app.modules.delivery.router import router as delivery_router

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Sirius.Food API")

app.include_router(users_router, prefix="/users", tags=["users"])
app.include_router(menu_router, prefix="/menu", tags=["menu"])
app.include_router(orders_router, prefix="/orders", tags=["orders"])
app.include_router(delivery_router, prefix="/delivery", tags=["delivery"])
```

### A.3. `app/database.py`

```python
"""
Модуль инициализации подключения к СУБД PostgreSQL.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://sirius:sirius@localhost:5432/sirius_food",
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Генератор сессии базы данных для использования в Depends."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

### A.4. `app/models.py`

```python
"""
Определение ORM-моделей предметной области «Сириус.Еда».
"""
from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False)
    phone = Column(String, nullable=True)
    balance = Column(Float, default=0.0)
    is_blocked = Column(Boolean, default=False)


class MenuItem(Base):
    __tablename__ = "menu_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    is_available = Column(Boolean, default=True)


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    item_id = Column(Integer, ForeignKey("menu_items.id"))
    quantity = Column(Integer, nullable=False)
    status = Column(String, default="processing")

    user = relationship("User")
    item = relationship("MenuItem")


class Delivery(Base):
    __tablename__ = "deliveries"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    courier_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String, default="pending")

    order = relationship("Order")
    courier = relationship("User")
```

### A.5. `app/schemas.py`

```python
"""
Pydantic-схемы для валидации входных и выходных данных.
"""
from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    phone: str | None = None


class UserResponse(BaseModel):
    id: int
    email: str
    balance: float

    class Config:
        from_attributes = True


class MenuItemCreate(BaseModel):
    name: str
    price: float


class MenuItemUpdate(BaseModel):
    name: str | None = None
    price: float | None = None
    is_available: bool | None = None


class OrderCreate(BaseModel):
    user_id: int
    item_id: int
    quantity: int


class DeliveryAssign(BaseModel):
    order_id: int
    courier_id: int
```

### A.6. `app/modules/orders/router.py` (MVP-версия)

```python
"""
Модуль управления заказами.
В исходной MVP-версии содержит смешение слоёв: HTTP-обработка,
бизнес-проверки и SQL-запросы находятся в одной функции.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Order, User, MenuItem
from app.schemas import OrderCreate

router = APIRouter()


@router.post("/create")
def create_order(payload: OrderCreate, db: Session = Depends(get_db)):
    # Блок 1: Первичная техническая валидация параметров запроса.
    if payload.quantity <= 0:
        raise HTTPException(
            status_code=400,
            detail="Количество должно быть больше нуля",
        )

    # Блок 2: Бизнес-проверки предметной области с обращением к СУБД.
    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    item = db.query(MenuItem).filter(MenuItem.id == payload.item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Блюдо не найдено")

    if not item.is_available:
        raise HTTPException(status_code=400, detail="Блюдо недоступно")

    total_cost = item.price * payload.quantity
    if user.balance < total_cost:
        raise HTTPException(
            status_code=400,
            detail="Недостаточно средств на балансе студента",
        )

    # Блок 3: Инфраструктурный код сохранения изменений.
    user.balance -= total_cost

    new_order = Order(
        user_id=payload.user_id,
        item_id=payload.item_id,
        quantity=payload.quantity,
        status="processing",
    )
    db.add(new_order)
    db.commit()
    db.refresh(new_order)

    return {"status": "success", "order_id": new_order.id}
```

### A.7. `app/modules/users/router.py` (MVP-версия)

```python
"""
Модуль управления пользователями.
В исходной MVP-версии содержит смешение слоёв.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User
from app.schemas import UserCreate

router = APIRouter()


@router.post("/register")
def register_user(payload: UserCreate, db: Session = Depends(get_db)):
    # Проверка корректности email выполняется Pydantic (EmailStr).
    # Проверка уникальности email требует обращения к СУБД.
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Пользователь с таким email уже зарегистрирован",
        )

    # Техническая проверка наличия телефона.
    if payload.phone and len(payload.phone) < 10:
        raise HTTPException(
            status_code=400,
            detail="Некорректный формат номера телефона",
        )

    # Создание пользователя с нулевым балансом.
    new_user = User(
        email=payload.email,
        phone=payload.phone,
        balance=0.0,
        is_blocked=False,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "status": "success",
        "user_id": new_user.id,
        "email": new_user.email,
    }


@router.post("/{user_id}/topup")
def top_up_balance(user_id: int, amount: float, db: Session = Depends(get_db)):
    # Техническая проверка положительности суммы пополнения.
    if amount <= 0:
        raise HTTPException(
            status_code=400,
            detail="Сумма пополнения должна быть положительной",
        )

    # Бизнес-правило: пополнение запрещено для заблокированных пользователей.
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    if user.is_blocked:
        raise HTTPException(
            status_code=403,
            detail="Пользователь заблокирован. Пополнение невозможно",
        )

    # Бизнес-правило: максимальная сумма одного пополнения.
    if amount > 50000:
        raise HTTPException(
            status_code=400,
            detail="Максимальная сумма пополнения — 50000 рублей",
        )

    user.balance += amount
    db.add(user)
    db.commit()
    db.refresh(user)

    return {"status": "success", "new_balance": user.balance}
```

### A.8. `app/modules/menu/router.py` (MVP-версия)

```python
"""
Модуль управления меню столовой.
В исходной MVP-версии содержит смешение слоёв.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import MenuItem
from app.schemas import MenuItemCreate, MenuItemUpdate

router = APIRouter()


@router.post("/items")
def create_menu_item(payload: MenuItemCreate, db: Session = Depends(get_db)):
    # Техническая валидация цены и названия.
    if payload.price <= 0:
        raise HTTPException(
            status_code=400,
            detail="Цена должна быть положительной",
        )

    if len(payload.name) < 2:
        raise HTTPException(
            status_code=400,
            detail="Название блюда слишком короткое",
        )

    # Бизнес-правило: название блюда должно быть уникальным.
    existing = db.query(MenuItem).filter(MenuItem.name == payload.name).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Блюдо с таким названием уже существует",
        )

    new_item = MenuItem(
        name=payload.name,
        price=payload.price,
        is_available=True,
    )
    db.add(new_item)
    db.commit()
    db.refresh(new_item)

    return {"status": "success", "item_id": new_item.id}


@router.patch("/items/{item_id}")
def update_menu_item(
    item_id: int,
    payload: MenuItemUpdate,
    db: Session = Depends(get_db),
):
    # Поиск обновляемого блюда.
    item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Блюдо не найдено")

    # Техническая валидация нового значения цены.
    if payload.price is not None and payload.price <= 0:
        raise HTTPException(
            status_code=400,
            detail="Цена должна быть положительной",
        )

    # Применение изменений.
    if payload.name is not None:
        item.name = payload.name
    if payload.price is not None:
        item.price = payload.price
    if payload.is_available is not None:
        item.is_available = payload.is_available

    db.add(item)
    db.commit()
    db.refresh(item)

    return {"status": "success", "item_id": item.id}
```

### A.9. `app/modules/delivery/router.py` (MVP-версия)

```python
"""
Модуль управления доставкой.
В исходной MVP-версии содержит смешение слоёв.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Delivery, Order, User
from app.schemas import DeliveryAssign

router = APIRouter()


@router.post("/assign")
def assign_courier(payload: DeliveryAssign, db: Session = Depends(get_db)):
    # Проверка существования заказа.
    order = db.query(Order).filter(Order.id == payload.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Заказ не найден")

    # Бизнес-правило: назначить курьера можно только на оплаченный заказ.
    if order.status != "paid":
        raise HTTPException(
            status_code=400,
            detail="Курьера можно назначить только на оплаченный заказ",
        )

    # Проверка существования курьера.
    courier = db.query(User).filter(User.id == payload.courier_id).first()
    if not courier:
        raise HTTPException(status_code=404, detail="Курьер не найден")

    if courier.is_blocked:
        raise HTTPException(
            status_code=403,
            detail="Курьер заблокирован и не может быть назначен",
        )

    # Бизнес-правило: один курьер — одна активная доставка.
    active = db.query(Delivery).filter(
        Delivery.courier_id == payload.courier_id,
        Delivery.status == "in_progress",
    ).first()
    if active:
        raise HTTPException(
            status_code=400,
            detail="У курьера уже есть активная доставка",
        )

    # Создание записи о доставке.
    new_delivery = Delivery(
        order_id=payload.order_id,
        courier_id=payload.courier_id,
        status="in_progress",
    )
    db.add(new_delivery)
    db.commit()
    db.refresh(new_delivery)

    return {"status": "success", "delivery_id": new_delivery.id}


@router.patch("/{delivery_id}/complete")
def complete_delivery(delivery_id: int, db: Session = Depends(get_db)):
    delivery = db.query(Delivery).filter(Delivery.id == delivery_id).first()
    if not delivery:
        raise HTTPException(status_code=404, detail="Доставка не найдена")

    if delivery.status == "completed":
        raise HTTPException(
            status_code=400,
            detail="Доставка уже завершена",
        )

    if delivery.status == "cancelled":
        raise HTTPException(
            status_code=400,
            detail="Отменённую доставку нельзя завершить",
        )

    delivery.status = "completed"

    # Синхронное обновление статуса заказа.
    order = db.query(Order).filter(Order.id == delivery.order_id).first()
    if order:
        order.status = "delivered"
        db.add(order)

    db.add(delivery)
    db.commit()

    return {"status": "success"}
```

### A.10. `docker-compose.yml`

```yaml
version: "3.9"

services:
  db:
    image: postgres:15
    environment:
      POSTGRES_USER: sirius
      POSTGRES_PASSWORD: sirius
      POSTGRES_DB: sirius_food
    ports:
      - "5432:5432"
    volumes:
      - pg_data:/var/lib/postgresql/data

  redis:
    image: redis:7
    ports:
      - "6379:6379"

volumes:
  pg_data:
```

### A.11. `requirements.txt`

```text
fastapi==0.110.0
uvicorn[standard]==0.29.0
sqlalchemy==2.0.29
psycopg2-binary==2.9.9
pydantic[email]==2.6.4
python-dotenv==1.0.1
```

## Приложение Б. Рекомендуемая структура после рефакторинга модуля `orders`

```text
app/
└── modules/
    └── orders/
        ├── __init__.py
        ├── router.py       # Транспортный слой
        ├── service.py      # Слой бизнес-логики
        └── repository.py   # Инфраструктурный слой
```
