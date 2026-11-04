# Лабораторная работа № 6. Микросервис доставки на gRPC

В «Сириус.Еде» операции доставки выполняет отдельный процесс. FastAPI принимает прежние HTTP-запросы, проверяет JWT и роли и передаёт вызовы сервису доставки. Сделаны оба потоковых сценария из [задания](task.md), поскольку критерий на 10 баллов включает трекинг и чат.

## Архитектура

```text
Swagger / HTTP-клиент
        |
        | HTTP + JWT
        v
FastAPI :8000 ─── DeliveryGrpcClient ── gRPC :50051 ── delivery_server.py
        |                                                      |
        | пользователи, заказы, меню                           | DeliveryService
        v                                                      v
   PostgreSQL <────────────────────────────────── PostgresDeliveryRepository
```

- `proto/delivery.proto` задаёт три обычных RPC и два потоковых. `delivery_pb2.py` содержит классы сообщений, а `delivery_pb2_grpc.py` содержит клиентскую заглушку и код регистрации обработчиков.
- `app/modules/delivery/router.py` проверяет роли и вызывает адаптер. Назначает администратор, завершает назначенный курьер, читают курьер и владелец заказа. Тестовый режим `REPOSITORY=memory` по-прежнему использует локальные данные.
- `grpc_client.py` собирает protobuf-запросы и ограничивает ожидание пятью секундами. Серверные ошибки переводятся обратно в ошибки приложения, а роутер возвращает HTTP 400, 403 или 404. Недоступность даёт 503, таймаут даёт 504.
- `delivery_server.py` открывает сессию БД на операцию и вызывает существующий `DeliveryService`. Сервис проверяет оплату заказа, роль, блокировку и занятость курьера. При завершении репозиторий одним коммитом сохраняет статусы доставки `completed` и заказа `delivered`.
- `GetDelivery` принимает идентификатор доставки для старого HTTP-маршрута или идентификатор заказа, как в методичке. При поиске по заказу берётся последняя созданная доставка. Для проверки доступа монолит передаёт ID пользователя из JWT. gRPC-сервер слушает только локальный интерфейс и доверяет вызывающему процессу.
- `TrackDelivery` после проверки доступа отправляет три демонстрационных статуса с интервалом в две секунды. `ChatWithCourier` сразу возвращает имитацию ответа курьера на каждое сообщение в том же потоке. `delivery_stream_client.py` проверяет оба сценария из консоли.

## Запуск

Из папки проекта с Python 3.11 или новее:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Если .env уже есть, сохраните его и проверьте настройки.
test -f .env || cp .env.example .env
docker compose up -d db redis
alembic upgrade head
```

Для демонстрации в `.env` нужен собственный `SECRET_KEY`, адрес общей PostgreSQL, `REPOSITORY=postgres` и `DEBUG=True` для Swagger. Сгенерированные файлы уже в проекте. После изменения контракта их можно обновить командой:

```bash
python -m grpc_tools.protoc -Iproto --python_out=. --grpc_python_out=. proto/delivery.proto
```

Первый терминал:

```bash
source .venv/bin/activate
python delivery_server.py
```

Второй терминал:

```bash
source .venv/bin/activate
uvicorn app.main:app --reload
```

## Демонстрация

1. Откройте [Swagger](http://127.0.0.1:8000/docs). Для проверки нужны администратор, студент, курьер и заказ студента со статусом `paid`. Если база пустая, зарегистрируйте пользователей через `POST /users/register`, затем назначьте роли и добавьте заказ в локальной базе:

   ```bash
   docker compose exec -T db psql -U sirius -d sirius_food <<'SQL'
   UPDATE users SET role_id = (SELECT id FROM roles WHERE name = 'admin')
   WHERE email = 'admin@sirius.ru';
   UPDATE users SET role_id = (SELECT id FROM roles WHERE name = 'courier')
   WHERE email = 'courier@sirius.ru';
   WITH dish AS (
       INSERT INTO menu_items (name, price, is_available)
       VALUES ('Суп для демонстрации', 100, true) RETURNING id
   )
   INSERT INTO orders (user_id, item_id, quantity, status, created_at)
   SELECT users.id, dish.id, 1, 'paid', now()
   FROM users CROSS JOIN dish WHERE users.email = 'student@sirius.ru'
   RETURNING id AS order_id, user_id AS student_id;
   SELECT id AS courier_id FROM users WHERE email = 'courier@sirius.ru';
   SQL
   ```

2. Войдите администратором через `POST /auth/login`. С его Bearer-токеном вызовите `POST /delivery/assign`, передав `order_id` и `courier_id`. FastAPI вызывает `AssignCourier`, gRPC-сервер сохраняет доставку, а монолит возвращает её `delivery_id`.
3. Войдите студентом и проверьте `GET /delivery/{delivery_id}` с его токеном. Запустите потоковые сценарии из третьего терминала. Подставьте ID своей доставки и студента вместо `1` и `2`.

   ```bash
   source .venv/bin/activate
   python delivery_stream_client.py track 1 2
   python delivery_stream_client.py chat "Где заказ?" "Спасибо!"
   ```

4. Вызовите `PATCH /delivery/{delivery_id}/complete` с токеном назначенного курьера. Повторный GET от студента покажет `completed`. Если остановить gRPC-сервер и повторить GET, FastAPI вернёт 503.

## Вывод проверки

```text
Delivery gRPC Server running on port 50051
AssignCourier: order_id=1, delivery_id=1
POST /delivery/assign 200 {"status":"success","delivery_id":1}
GET /delivery/1 200 {"id":1,"order_id":1,"courier_id":3,"status":"in_progress"}
GET /delivery/1 403 {"detail":"Нет доступа к этой доставке"}
in_progress
on_the_way
delivered
Курьер получил сообщение: Где заказ?
Курьер получил сообщение: Спасибо!
PATCH /delivery/1/complete 200 {"status":"success"}
GET /delivery/1 200 {"id":1,"order_id":1,"courier_id":3,"status":"completed"}
GET /delivery/1 504 {"detail":"Сервис доставки не ответил за 5 секунд"}
GET /delivery/1 503 {"detail":"Сервис доставки недоступен"}
```

Интеграционная проверка выполнена на двух процессах с временной базой PostgreSQL. Набор тестов с Redis — `45 passed`.

## Вопросы для защиты

- Зачем выделять доставку? Её можно запускать отдельным процессом и менять серверную реализацию, пока клиент продолжает обращаться к прежнему HTTP API.
- Почему gRPC? Между Python-процессами есть общий protobuf-контракт, из которого генерируется код обеих сторон. HTTP/2 позволяет передавать ответы потоком в одном вызове.
- Что происходит при сбое? При разрыве соединения получаем `UNAVAILABLE` и HTTP 503. Если сервер не успел ответить за пять секунд, получаем `DEADLINE_EXCEEDED` и HTTP 504. Запросы изменения автоматически не повторяются.
- Зачем сервису своя БД? Своя схема уменьшает связанность миграций и даёт сервису владение данными. Здесь общая БД упрощает перенос, так как завершение меняет доставку и заказ одной транзакцией.
- Чем отличаются RPC? Unary даёт один ответ на один запрос. Server Streaming даёт несколько статусов на один запрос. В двунаправленном потоке и клиент, и сервер отправляют несколько сообщений в рамках одного вызова.
- Где здесь Strangler Fig? HTTP-маршруты доставки сохранились, а их рабочий путь перенаправлен на новый процесс. Остальные функции по-прежнему обслуживает монолит.
- Зачем нужен адаптер? Он собирает сетевые сообщения, задаёт дедлайн и переводит gRPC-ошибки. Правила доставки остаются в `DeliveryService`.

[Лабораторная № 5](README-lab5.md)
