# Практическая работа № 6
Удушение монолита: вынос модуля delivery в gRPC-микросервис
Дисциплина: Разработка программных модулей и приложений для серверов
Тема: Межсервисное взаимодействие на базе gRPC и паттерн Strangler Fig
Продолжительность: 2 академических часа (90 минут) + самостоятельная работа
Проект: сквозной пет-проект «Сириус.Еда»
Операционная система: Ubuntu 22.04 LTS или новее


## Цели работы

В ходе выполнения лабораторной работы вы:
Освоите принципы межсервисного взаимодействия на базе бинарного протокола gRPC.
Научитесь описывать контракты с помощью Protocol Buffers (.proto).
Реализуете отдельный gRPC-микросервис, вынеся бизнес-логику модуля delivery из монолита.
Интегрируете gRPC-клиент в монолит, заменив прямые вызовы к базе данных на сетевые вызовы.
Примените паттерн Strangler Fig для постепенного отказа от монолитной архитектуры.
Обеспечите отказоустойчивость: научитесь обрабатывать сетевые ошибки и таймауты.
Дополнительно (для 9–10 баллов):
Реализуете Server Streaming для трекинга доставки в реальном времени.
Реализуете Bidirectional Streaming для чата между клиентом и курьером.



## Критерии оценивания (10-балльная шкала)

Баллы
Оценка
Что нужно сделать
0–3
Неудовлетворительно (2)
.proto не создан или содержит ошибки. gRPC-сервер не запускается. Интеграция с монолитом не выполнена.
4–5
Удовлетворительно (3)
.proto создан, код сгенерирован. Однако gRPC-сервер не отвечает на запросы, или монолит не может к нему подключиться.
6–7
Хорошо (4)
gRPC-сервер работает. Монолит успешно вызывает методы gRPC-сервиса. Два процесса запущены параллельно и корректно взаимодействуют.
8
Отлично (5)
Все требования уровня 6–7 выполнены. Дополнительно: реализована обработка сетевых ошибок (UNAVAILABLE, таймауты). Оформлен README.md с архитектурной схемой. Устная защита демонстрирует понимание.
9
Отлично с плюсом (5+)
Все требования уровня 8 выполнены. Дополнительно: реализован Server Streaming (метод TrackDelivery, транслирующий статусы доставки).
10
Отлично с двойным плюсом (5++)
Все требования уровня 9 выполнены. Дополнительно реализовано: Bidirectional Streaming (чат с курьером).


## 1. Пререквизиты

Для выполнения работы вам потребуется:
Ubuntu 22.04 LTS;
Python 3.11 или новее;
Docker Engine и Docker Compose (запущены db и redis);
Git;
выполненные лабораторные работы № 2–5 (монолит отрефакторен, внедрены безопасность, кеш и фоновые задачи).
Установка дополнительных зависимостей
Нам понадобятся библиотеки для работы с gRPC:
grpcio — runtime-библиотека, обеспечивающая сетевую передачу по HTTP/2.
grpcio-tools — компилятор, который генерирует Python-код (Stub и Message-классы) из .proto-файла.

```bash
source .venv/bin/activate
pip install grpcio grpcio-tools
```

Запуск инфраструктуры
Убедимся, что PostgreSQL и Redis запущены:

```bash
docker compose up -d db redis
```



## 2. Теоретическое введение

2.1. Паттерн Strangler Fig (Душитель)
Паттерн подразумевает постепенную замену частей монолитной системы на микросервисы. Вы не переписываете всё приложение сразу. Вместо этого вы «вырезаете» один модуль (в нашем случае delivery), разворачиваете его как отдельный сервис и перенаправляете вызовы к нему. Монолит при этом продолжает работать, но становится «худее».
2.2. Архитектура gRPC
В gRPC взаимодействие строится на трёх компонентах:
Контракт (.proto) — строгое описание методов и типов данных.
Сервер — класс, наследующий сгенерированный Servicer, содержащий бизнес-логику.
Клиент (Stub) — сгенерированный класс, который позволяет вызывать методы сервера так, как будто они находятся локально.
2.3. Ключевой архитектурный принцип
В Clean Architecture gRPC-клиент должен находиться в инфраструктурном слое. Бизнес-логика (Service) не должна знать, что данные пришли по сети. Она должна работать с абстракцией (интерфейсом), как мы делали это с Repository.



## 3. Практическая часть


### Этап 1. Создание gRPC-контракта

Что делаем: создаём файл delivery.proto, в котором описываем методы, которые монолит будет вызывать у нового микросервиса.
Зачем: .proto-файл — это единый источник правды. Он гарантирует, что клиент и сервер говорят на одном языке.
Создайте в корне проекта папку proto и файл proto/delivery.proto:

```protobuf
syntax = "proto3";

// Пакет для генерации Python-кода.
package delivery;

// Описание сервиса доставки.
service DeliveryService {
  // Назначение курьера на заказ.
  rpc AssignCourier(AssignCourierRequest) returns (AssignCourierResponse);

  // Завершение доставки.
  rpc CompleteDelivery(CompleteDeliveryRequest) returns (CompleteDeliveryResponse);

  // Получение информации о доставке.
  rpc GetDelivery(GetDeliveryRequest) returns (GetDeliveryResponse);
}

// --- Сообщения для AssignCourier ---
message AssignCourierRequest {
  int32 order_id = 1;
  int32 courier_id = 2;
}

message AssignCourierResponse {
  int32 delivery_id = 1;
  string status = 2;
}

// --- Сообщения для CompleteDelivery ---
message CompleteDeliveryRequest {
  int32 delivery_id = 1;
}

message CompleteDeliveryResponse {
  string status = 1;
}

// --- Сообщения для GetDelivery ---
message GetDeliveryRequest {
  int32 order_id = 1;
}

message GetDeliveryResponse {
  int32 id = 1;
  string status = 2;
  int32 courier_id = 3;
}
```


### Этап 2. Генерация Python-кода

Что делаем: запускаем компилятор protoc, который сгенерирует два Python-файла на основе нашего контракта.
Зачем: писать сериализацию Protobuf и сетевую обвязку вручную — долго и чревато ошибками. Компилятор делает это автоматически.
Выполните в терминале:

```bash
python -m grpc_tools.protoc -Iproto --python_out=. --grpc_python_out=. proto/delivery.proto
```

Что произошло: в корне проекта появились файлы delivery_pb2.py (классы сообщений) и delivery_pb2_grpc.py (серверные и клиентские заглушки).


### Этап 3. Реализация gRPC-сервера

Что делаем: создаём отдельный процесс-сервер, который будет обслуживать вызовы от монолита.
Зачем: это и есть наш новый микросервис. Он содержит бизнес-логику доставки.
Создайте файл delivery_server.py в корне проекта (рядом с app):

```python
"""
Микросервис доставки. Работает как отдельный процесс.
Слушает порт 50051 и обслуживает gRPC-вызовы от монолита.
"""
import grpc
from concurrent import futures
import time

# Импорт сгенерированных классов.
import delivery_pb2
import delivery_pb2_grpc

# Импорт инфраструктуры монолита для работы с БД.
# В реальном проекте у микросервиса была бы своя БД и модели.
from app.database import SessionLocal
from app.models import Delivery, Order


class DeliveryServiceServicer(delivery_pb2_grpc.DeliveryServiceServicer):
    """
    Реализация бизнес-логики модуля доставки.
    """

    def AssignCourier(self, request, context):
        """Назначение курьера на заказ."""
        db = SessionLocal()
        try:
            # Проверка, что заказ существует.
            order = db.query(Order).filter(Order.id == request.order_id).first()
            if not order:
                context.abort(grpc.StatusCode.NOT_FOUND, "Order not found")

            # Создание доставки.
            delivery = Delivery(
                order_id=request.order_id,
                courier_id=request.courier_id,
                status="in_progress"
            )
            db.add(delivery)
            db.commit()
            db.refresh(delivery)

            return delivery_pb2.AssignCourierResponse(
                delivery_id=delivery.id,
                status=delivery.status
            )
        finally:
            db.close()

    def CompleteDelivery(self, request, context):
        """Завершение доставки."""
        db = SessionLocal()
        try:
            delivery = db.query(Delivery).filter(Delivery.id == request.delivery_id).first()
            if not delivery:
                context.abort(grpc.StatusCode.NOT_FOUND, "Delivery not found")

            delivery.status = "completed"
            db.commit()

            return delivery_pb2.CompleteDeliveryResponse(status=delivery.status)
        finally:
            db.close()

    def GetDelivery(self, request, context):
        """Получение информации о доставке по ID заказа."""
        db = SessionLocal()
        try:
            delivery = db.query(Delivery).filter(Delivery.order_id == request.order_id).first()
            if not delivery:
                context.abort(grpc.StatusCode.NOT_FOUND, "Delivery not found")

            return delivery_pb2.GetDeliveryResponse(
                id=delivery.id,
                status=delivery.status,
                courier_id=delivery.courier_id
            )
        finally:
            db.close()


def serve():
    """Запуск gRPC-сервера."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    delivery_pb2_grpc.add_DeliveryServiceServicer_to_server(
        DeliveryServiceServicer(), server
    )
    server.add_insecure_port('[::]:50051')
    server.start()
    print("Delivery gRPC Server running on port 50051")
    try:
        while True:
            time.sleep(86400)
    except KeyboardInterrupt:
        server.stop(0)


if __name__ == '__main__':
    serve()
```


### Этап 4. Интеграция клиента в монолит

Что делаем: создаём класс-клиент в монолите, который будет общаться с gRPC-сервером.
Зачем: бизнес-логика монолита (Service) не должна знать про сеть. Мы создаём адаптер (как Repository), который скрывает gRPC.
Создайте файл app/modules/delivery/grpc_client.py:

```python
"""
gRPC-клиент для общения с микросервисом доставки.
Является адаптером между бизнес-логикой монолита и сетью.
"""
import grpc
import delivery_pb2
import delivery_pb2_grpc


class DeliveryGrpcClient:
    def __init__(self, host: str = "localhost", port: int = 50051):
        # Создаём канал. insecure_channel — для локальной разработки без TLS.
        self.channel = grpc.insecure_channel(f"{host}:{port}")
        self.stub = delivery_pb2_grpc.DeliveryServiceStub(self.channel)

    def assign_courier(self, order_id: int, courier_id: int) -> dict:
        try:
            request = delivery_pb2.AssignCourierRequest(
                order_id=order_id, courier_id=courier_id
            )
            # Таймаут 5 секунд, чтобы не ждать вечно, если сервис упал.
            response = self.stub.AssignCourier(request, timeout=5)
            return {"delivery_id": response.delivery_id, "status": response.status}
        except grpc.RpcError as e:
            self._handle_error(e)

    def complete_delivery(self, delivery_id: int) -> dict:
        try:
            request = delivery_pb2.CompleteDeliveryRequest(delivery_id=delivery_id)
            response = self.stub.CompleteDelivery(request, timeout=5)
            return {"status": response.status}
        except grpc.RpcError as e:
            self._handle_error(e)

    def get_delivery(self, order_id: int) -> dict:
        try:
            request = delivery_pb2.GetDeliveryRequest(order_id=order_id)
            response = self.stub.GetDelivery(request, timeout=5)
            return {
                "id": response.id,
                "status": response.status,
                "courier_id": response.courier_id
            }
        except grpc.RpcError as e:
            self._handle_error(e)

    def _handle_error(self, e: grpc.RpcError):
        """Обработка сетевых ошибок gRPC."""
        if e.code() == grpc.StatusCode.NOT_FOUND:
            raise ValueError("Object not found")
        if e.code() == grpc.StatusCode.UNAVAILABLE:
            raise ConnectionError("Delivery service is unavailable")
        if e.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
            raise TimeoutError("Delivery service timeout")
        raise RuntimeError(f"gRPC error: {e.details()}")
```


### Этап 5. Замена логики в монолите

Что делаем: в OrderService или DeliveryService монолита заменяем прямые вызовы к БД на вызовы DeliveryGrpcClient.
Зачем: монолит должен перестать работать с таблицей deliveries напрямую.
Откройте app/modules/delivery/router.py (или service.py, в зависимости от вашей структуры). Замените вызовы DeliveryRepository на DeliveryGrpcClient:

```python
# Пример для router.py
from app.modules.delivery.grpc_client import DeliveryGrpcClient

@router.post("/assign")
def assign_courier(payload: DeliveryAssign):
    client = DeliveryGrpcClient()
    try:
        result = client.assign_courier(payload.order_id, payload.courier_id)
        return {"status": "success", **result}
    except ValueError as e:
        raise HTTPException(404, str(e))
    except ConnectionError as e:
        raise HTTPException(503, str(e))
```


### Этап 6. Запуск и проверка

Что делаем: запускаем два процесса параллельно.
Терминал 1 (gRPC-сервер):

```bash
source .venv/bin/activate
python delivery_server.py
```

Ожидаемый вывод: Delivery gRPC Server running on port 50051.
Терминал 2 (Монолит):

```bash
source .venv/bin/activate
uvicorn app.main:app --reload
```

Проверка в Swagger: выполните запрос POST /delivery/assign. Убедитесь, что заказ создан, а в логах gRPC-сервера появилась запись об обработке запроса.


## 4. Задание для самостоятельной работы (9–10 баллов)

Вам необходимо доработать систему, выбрав одно из заданий:
Вариант А (9 баллов). Server Streaming для трекинга доставки.
Добавьте в .proto метод TrackDelivery(TrackDeliveryRequest) returns (stream DeliveryStatus).
Сгенерируйте код.
На сервере реализуйте метод, который отправляет статусы (in_progress → on_the_way → delivered) с задержкой в 2 секунды.
На клиенте (в монолите) напишите скрипт, который подписывается на этот поток и выводит статусы в консоль.
Вариант Б (10 баллов). Bidirectional Streaming для чата.
Добавьте в .proto метод ChatWithCourier(stream ChatMessage) returns (stream ChatMessage).
Реализуйте сервер, который принимает сообщения от клиента и отправляет ответы в реальном времени.
Напишите клиент, который отправляет сообщение и ждет ответа.
Задание сдаётся в виде:
двух запущенных процессов (демонстрация);
README.md с архитектурной схемой (монолит + gRPC-сервис);
устной защиты.

## 5. Контрольные вопросы для защиты работы

Зачем выносить модуль delivery в отдельный сервис? Какие проблемы это решает?
Почему для межсервисного общения выбран gRPC, а не REST?
Что произойдёт, если gRPC-сервис недоступен? Как обработать эту ошибку?
Почему в идеальном микросервисе у delivery должна быть своя БД? Какие проблемы возникают при использовании общей БД?
Чем Server Streaming отличается от Unary? Приведите пример.
Что такое паттерн Strangler Fig и как он связан с выносом delivery?
Какую роль играет DeliveryGrpcClient в архитектуре монолита? Почему он находится в инфраструктурном слое?

## 6. Приложение: Структура проекта после внедрения


```text
sirius_food/
├── app/
│   ├── modules/
│   │   └── delivery/
│   │       ├── grpc_client.py    # gRPC-клиент (инфраструктура)
│   │       ├── router.py         # HTTP-эндпоинты (транспорт)
│   │       └── ...
│   ├── main.py
│   └── ...
├── proto/
│   └── delivery.proto            # Контракт
├── delivery_pb2.py               # Сгенерированные сообщения
├── delivery_pb2_grpc.py          # Сгенерированные Stub и Servicer
├── delivery_server.py            # gRPC-сервер (микросервис)
├── docker-compose.yml
└── requirements.txt
```
