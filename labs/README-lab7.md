# Лабораторная работа № 7. Event-driven архитектура

В «Сириус.Еде» кухня и доставка получают событие `OrderPaid` через RabbitMQ. У каждого consumer своя очередь, поэтому оба независимо обрабатывают оплату. Сделаны идемпотентность, DLQ, Saga с компенсацией оплаты и Transactional Outbox из задания.

## Архитектура

```text
POST /orders/create -> Order(processing)
POST /orders/{id}/pay -> баланс + paid + outbox (одна транзакция)
                                          |
                                     outbox_worker
                                          |
                                   sirius_events (topic)
                /                         |                       \
         order.paid                 order.paid              delivery.failed
              |                           |                       |
        kitchen_queue              delivery_queue            orders_queue
              |                           |                       |
      kitchen_consumer             delivery_worker          orders_consumer
              |                           |                       |
        KitchenOrder            поиск свободного курьера    возврат + cancelled
                                  /               \               |
                           in_progress          failed      outbox: order.cancelled
                                                  |               |
                                     outbox: delivery.failed      |
                                                                  v
                                sirius_events -> kitchen_queue -> KitchenOrder(cancelled)

Ошибка consumer -> dlx_exchange (direct) -> kitchen_dlq / delivery_dlq / orders_dlq
```

RabbitMQ отвечает за события между компонентами. Redis остаётся брокером Celery и хранилищем кеша из предыдущих работ. Доставка автоматически назначает свободного курьера. gRPC из лабораторной № 6 используется для чтения и завершения доставки, трекинга и чата; ручное назначение также возможно до автоматической обработки заказа.

## Запуск

Нужны Python 3.11 или новее и Docker Compose. Из папки проекта:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Существующий .env не перезаписываем.
test -f .env || cp .env.example .env
docker compose up -d db redis rabbitmq
alembic upgrade head
```

В `.env` нужны собственный `SECRET_KEY`, адрес PostgreSQL, `REPOSITORY=postgres` и `DEBUG=True` для Swagger. Новая настройка имеет значение по умолчанию:

```dotenv
RABBITMQ_URL=amqp://sirius:sirius@localhost:5672/
```

При первом запуске RabbitMQ нужно немного времени. Проверка готовности:

```bash
docker exec sirius_rabbitmq rabbitmq-diagnostics -q ping
python -m app.workers.dlq_setup
```

Ожидается `Ping succeeded`, затем `DLQ настроена: kitchen_dlq, delivery_dlq, orders_dlq.` Скрипт создаёт три рабочие очереди, три DLQ и связи с exchange. Ту же настройку автоматически выполняют publisher и consumer'ы, поэтому события сохраняются и до запуска consumer'ов.

Откройте отдельный терминал для каждого процесса. Во всех сначала выполните `source .venv/bin/activate`:

```bash
# Терминал 1: HTTP API
uvicorn app.main:app --reload
```

```bash
# Терминал 2: кухня
python -m app.workers.kitchen_consumer
```

```bash
# Терминал 3: доставка
python delivery_worker.py
```

```bash
# Терминал 4: отправка событий из outbox
python -m app.workers.outbox_worker
```

```bash
# Терминал 5: gRPC-сервис для операций с доставкой
python delivery_server.py
```

```bash
# Терминал 6: компенсация оплаты при неудачной доставке
python -m app.workers.orders_consumer
```

Для выполнения прежних задач PDF, email и SMS отдельно запускается Celery:

```bash
celery -A app.core.celery_app worker -Q default --loglevel=info
```

Без Celery эти задачи остаются в Redis; consumer'ы RabbitMQ работают отдельными процессами. Режим `REPOSITORY=memory` сохранён для прежних тестов в одном процессе. Демонстрация событий и outbox выполняется с PostgreSQL.

## Как устроен код

- `app/core/events.py` создаёт `OrderPaid`, `DeliveryFailed` и `OrderCancelled`. В каждом есть UUID события, ID заказа и владельца. В `OrderPaid` сохранена списанная сумма, а `DeliveryFailed` ссылается на UUID исходной оплаты через `payment_event_id`. При повторной отправке UUID не меняется.
- `app/modules/orders/service.py` проверяет пользователя, доступность блюда и право оплатить заказ. `create_order` сохраняет заказ со статусом `processing`, не списывает деньги и не создаёт событие. `pay_order` списывает деньги, переводит заказ в `paid` и сохраняет `OrderPaid` в outbox. До оплаты заказ не показывается кухне. Повторная оплата `paid` возвращает заказ без нового списания.
- `app/modules/orders/repository.py` сохраняет баланс, статус `paid` и запись `outbox` одним коммитом. При оплате существующего заказа блокируется строка заказа, при списании блокируется пользователь. Это защищает от одновременных запросов. Сервис не обращается к RabbitMQ напрямую.
- `app/workers/outbox_worker.py` выбирает неопубликованную запись с `FOR UPDATE SKIP LOCKED`. После подтверждения RabbitMQ ставит `published=True`. При ошибке транзакция откатывается, запись остаётся неопубликованной. Через две секунды воркер пробует снова. Если событий несколько, успешные отправляются подряд без этой паузы.
- `app/core/rabbitmq.py` объявляет durable topic exchange `sirius_events`, рабочие очереди и DLQ. Кухня слушает `order.paid` и `order.cancelled`, доставка — `order.paid`, обработчик заказов — `delivery.failed`. Сообщение persistent, публикация использует publisher confirms и `mandatory=True`. Очереди и данные RabbitMQ сохраняются в Docker volume.
- `app/workers/consumer.py` проверяет JSON и обязательные поля. Запись в `processed_events` и результат обработки сохраняются одной транзакцией. Первичный ключ состоит из имени consumer и `event_id`: кухня и доставка должны обработать одно событие каждая. `ON CONFLICT DO NOTHING` защищает и от одновременных повторов. После коммита отправляется ACK.
- `app/workers/kitchen_consumer.py` запускает обработчик кухни. На `OrderPaid` он создаёт `KitchenOrder(status="pending")`, на `OrderCancelled` ставит `cancelled`. У `order_id` есть уникальное ограничение. Если отмена пришла раньше оплаты, поздний `OrderPaid` не возобновит заказ.
- `delivery_worker.py` запускает обработчик доставки. Он ищет пользователя с ролью `courier`, без блокировки и активной доставки. Блокировка строки курьера с `SKIP LOCKED` не даёт двум delivery-worker назначить его одновременно. При успехе создаётся `Delivery(status="in_progress")`. Если свободного курьера нет, доставка получает `failed`, а событие `DeliveryFailed` сохраняется в outbox той же транзакцией. Если доставка уже была назначена через gRPC, повторная не создаётся.
- `app/workers/orders_consumer.py` слушает `DeliveryFailed`. В `compensate_payment` из `consumer.py` заказ блокируется, возвращается сумма из исходного `OrderPaid`, статус меняется на `cancelled`, а `OrderCancelled` записывается в outbox. Возврат и новое событие фиксируются одним коммитом. Проверка статуса под блокировкой защищает и от нового `event_id` для той же неудачи: второй возврат не выполняется. Лог возврата появляется после коммита. Опубликованные события оплаты остаются в outbox, поскольку содержат исходную сумму для компенсации.
- `app/workers/dlq_setup.py` объявляет топологию отдельно. При исключении consumer делает reject без возврата в рабочую очередь: одна попытка обработки, затем соответствующая DLQ. Автоматического возврата из DLQ нет. После исправления причины сообщение можно отправить повторно.
- `app/models.py` и новая миграция добавляют `kitchen_orders`, `processed_events` и `outbox`. Общая PostgreSQL сохранена из лабораторной № 6.

Если процесс упадёт между коммитом consumer'а и ACK, RabbitMQ доставит событие повторно, а `processed_events` остановит повторное изменение данных. Если outbox-воркер упадёт после публикации, но до коммита `published=True`, он тоже отправит событие повторно. Поэтому outbox работает вместе с идемпотентностью.

## Демонстрация

1. Откройте [Swagger](http://127.0.0.1:8000/docs). Зарегистрируйте студента через `POST /users/register`, войдите через `POST /auth/login` и укажите access-токен в Authorize. Пополните свой баланс через `POST /users/{user_id}/topup?amount=1000`. Для успешной доставки также зарегистрируйте `courier@sirius.ru` и назначьте ему роль командой ниже.
2. Назначьте роль курьеру и, если меню пустое, добавьте тестовое блюдо в локальную базу:

   ```bash
   docker compose exec -T db psql -U sirius -d sirius_food <<'SQL'
   UPDATE users SET role_id = (SELECT id FROM roles WHERE name = 'courier')
   WHERE email = 'courier@sirius.ru';
   INSERT INTO menu_items (name, price, is_available)
   VALUES ('Суп для lab7', 100, true) RETURNING id;
   SQL
   ```

3. Вызовите `POST /orders/create` с ID блюда и `quantity: 2`. Заказ получит статус `processing`, баланс не изменится. Затем вызовите `POST /orders/{id}/pay` с полученным ID. Заказ станет `paid`, со студента спишется 200. Сначала событие попадёт в outbox, затем воркер отправит его в RabbitMQ. В терминалах появятся `[Kitchen] Принят заказ ...` и `[Delivery] Заказ ...: назначен курьер ...`. Доставка получит `in_progress`; ID курьера можно посмотреть в PostgreSQL.
4. В [RabbitMQ Management](http://localhost:15672) войдите как `sirius` / `sirius`. В Exchanges есть `sirius_events` и `dlx_exchange`, в Queues — `kitchen_queue`, `delivery_queue`, `orders_queue`, `kitchen_dlq`, `delivery_dlq`, `orders_dlq`. После обработки рабочие очереди пустые: сообщения подтверждены, результаты лежат в PostgreSQL.
5. Проверьте записи:

   ```bash
   docker compose exec -T db psql -U sirius -d sirius_food <<'SQL'
   SELECT id, routing_key, published, payload FROM outbox ORDER BY created_at;
   SELECT * FROM kitchen_orders ORDER BY id;
   SELECT id, order_id, courier_id, status FROM deliveries ORDER BY id;
   SELECT * FROM processed_events ORDER BY consumer, id;
   SQL
   ```

   При успешном назначении на оплату приходится одна запись outbox, одна запись кухни, одна доставка и две отметки `processed_events`. Если свободного курьера нет, добавляются события `DeliveryFailed` и `OrderCancelled`, деньги возвращаются, заказ и запись кухни становятся `cancelled`.

### Отдельная оплата

Создайте заказ через `POST /orders/create`, затем вызовите `/orders/{id}/pay` от владельца заказа. Статус изменится с `processing` на `paid`, появится событие. Повторный запрос не спишет деньги снова и не добавит событие. Чужой студент получит 403, запрос без токена — 401, отменённый заказ — 400. При недостатке средств создание разрешено, а оплата вернёт 400: заказ останется в `processing` и баланс не изменится.

### Saga: нет свободного курьера

Для проверки нужна ситуация, когда все курьеры заняты или заблокированы. В демонстрационной базе с одним курьером можно временно заблокировать его:

```bash
docker compose exec -T db psql -U sirius -d sirius_food <<'SQL'
UPDATE users SET is_blocked = true WHERE email = 'courier@sirius.ru';
SQL
```

Создайте и оплатите новый заказ. Доставка сохранит `DeliveryFailed`, обработчик заказов вернёт деньги на баланс, отменит заказ и сохранит `OrderCancelled`. Кухня получит отмену. В логах будут строки:

```text
[Delivery] Заказ ...: курьер не найден, сохранён DeliveryFailed
[Orders] Заказ ... отменён, возврат ... пользователю ...
[Kitchen] Отменён заказ ...
```

В outbox для этого заказа будут три записи с ключами `order.paid`, `delivery.failed`, `order.cancelled`. В `deliveries` останется `failed`, в `orders` и `kitchen_orders` — `cancelled`. Баланс вернётся к значению до оплаты. Связь между шагами идёт через события; отдельного управляющего Saga-процесса нет.

Скопируйте payload `delivery.failed` и отправьте его ещё несколько раз через exchange `sirius_events` с ключом `delivery.failed`. Повторного возврата и второго `OrderCancelled` быть не должно. Даже сообщение с новым UUID для того же заказа не вернёт деньги повторно: заказ уже отменён.

После демонстрации разблокируйте курьера:

```bash
docker compose exec -T db psql -U sirius -d sirius_food <<'SQL'
UPDATE users SET is_blocked = false WHERE email = 'courier@sirius.ru';
SQL
```

### Идемпотентность и DLQ

В Management откройте exchange `sirius_events`, раздел Publish message. Скопируйте `payload` из outbox, сохраните прежний `event_id`, укажите routing key `order.paid` и отправьте несколько раз. Оба consumer'а выведут `Повтор ... пропущен`. Число записей кухни и доставки не увеличится.

Там же отправьте `not-json` с ключом `order.paid`. Сообщение попадёт в обе рабочие очереди, обработка завершится ошибкой, и копии окажутся в `kitchen_dlq` и `delivery_dlq`. Синтаксически корректный JSON без обязательных полей тоже отклоняется. Следующее корректное событие продолжит обрабатываться. Невалидное сообщение с ключом `delivery.failed` попадёт в `orders_dlq`.

Если временно недоступна PostgreSQL, сообщение также уйдёт в DLQ. После восстановления базы его нужно переотправить вручную. Бесконечного `requeue` в этой работе нет.

### Проверка outbox при выключенном брокере

```bash
docker compose stop rabbitmq
```

Создайте ещё один заказ через Swagger и вызовите для него `/pay`. Оба HTTP-запроса успешно завершатся, при оплате деньги спишутся, в `outbox` останется `published=False`. Outbox-воркер будет писать об ошибке отправки. Кухня и доставка узнают об оплате после восстановления брокера:

```bash
docker compose start rabbitmq
```

Воркер отправит сохранённое событие и поставит `published=True`. Если курьера нет, далее выполнится Saga; её события также проходят через outbox. Consumer'ы подключаются через `connect_robust` и восстанавливают подписки. Все процессы оставьте запущенными на время этой проверки.

## Вывод проверки

Создание и оплата проверены через FastAPI TestClient на временной PostgreSQL. Пять запросов оплаты выполнялись одновременно. Проверены отсутствие события до оплаты, однократное списание и откат транзакции при ошибке записи события.

```text
POST /orders/create 200 {"status":"success","order_id":1}
После создания: status=processing, balance=500, outbox=0
Оплата чужого заказа: HTTP 403
POST /orders/1/pay, 5 параллельных запросов: HTTP 200
После оплаты: status=paid, balance=300, outbox=1, published=False
Недостаточно средств: создание HTTP 200, оплата HTTP 400, status=processing, balance=300
Ошибка записи события: баланс и статус откатились, outbox=1
Проверка разделения создания и оплаты завершена успешно.
```

Проверка Saga выполнена на временной PostgreSQL и отдельном RabbitMQ vhost. Кухня, обработчик заказов, outbox и два delivery-worker работали отдельными процессами:

```text
Создание: order=processing, balance=1000, outbox=0
Нет свободного курьера: order=cancelled, delivery=failed, kitchen=cancelled, balance=1000
Цена блюда изменена на 999: возвращены исходные 200; события OrderPaid -> DeliveryFailed -> OrderCancelled
Повторы DeliveryFailed с прежним и новыми event_id: возврат один раз, OrderCancelled один
Поздний OrderPaid после отмены: заказ и кухня остались cancelled
Свободный курьер: order=paid, delivery=in_progress, courier=5, balance=900
Один курьер занят, второй заблокирован: новый заказ отменён, balance=900
Два delivery-worker, два одновременных заказа: одно назначение, одна компенсация, balance=800
После перезапуска outbox: цепочка Saga завершена, все события published=True, balance=800
Битые сообщения: kitchen_dlq=1, delivery_dlq=1, orders_dlq=1
Проверка Saga на PostgreSQL и RabbitMQ завершена успешно.
```

Тесты сервисов, безопасности и шагов Saga: `50 passed`. Четыре теста Saga используют SQLite для проверки изменений данных и отката; блокировки и взаимодействие через брокер проверены отдельно на PostgreSQL и RabbitMQ. Им нужен Redis:

```bash
python -m unittest discover tests -v
```

## Вопросы для защиты

- Зачем событие вместо прямого gRPC-вызова? Оплата не ждёт кухню и доставку. У каждого своя очередь, и временно выключенный consumer обработает накопленные события после запуска.
- Чем отличаются exchange и queue? Exchange маршрутизирует сообщения по bindings, очередь хранит сообщения до обработки. У нас один topic exchange и три рабочие очереди: кухня и доставка получают `order.paid`, заказы — `delivery.failed`, кухня также получает `order.cancelled`.
- Как обеспечена идемпотентность? Результат и отметка `(consumer, event_id)` фиксируются одной транзакцией. Повторный event_id не вызывает обработку заново. Для кухни дополнительно уникален `order_id`.
- Почему At-Least-Once? При потере подтверждения отправитель не знает, успел ли получатель сохранить результат. Повторная доставка позволяет не потерять сообщение, а дубли убирает обработчик.
- Зачем DLQ? В ней сохраняются сообщения, обработка которых завершилась ошибкой. Они не возвращаются бесконечно в рабочую очередь, их можно изучить и переотправить.
- Что будет при падении consumer'а? До коммита транзакция откатится, неподтверждённое сообщение будет доставлено снова. После коммита, но до ACK, повтор обнаружится через `processed_events`.
- Чем событие отличается от команды? `OrderPaid` сообщает о состоявшемся факте и может быть интересно нескольким consumer'ам. `AssignCourier` — команда конкретному сервису выполнить действие.
- Как Saga решает проблему распределённых транзакций? Каждый сервис фиксирует локальный шаг. При неудаче выполняются компенсации, например возврат денег и отмена заказа. Здесь доставка публикует `DeliveryFailed`, обработчик заказов возвращает деньги и сохраняет `OrderCancelled`, а кухня отменяет свою запись. Это хореография: каждый обработчик реагирует на событие без общего координатора.
- Почему нельзя просто опубликовать событие после `commit`? Между коммитом и публикацией процесс или RabbitMQ может упасть. Заказ останется оплаченным без события. Outbox сохраняет событие вместе с оплатой.
- Outbox даёт Exactly-Once? Нет. После публикации воркер может упасть до отметки `published`. Событие отправится ещё раз с тем же UUID, поэтому consumer должен быть идемпотентным.

[Лабораторная № 6](README-lab6.md) · [Лабораторная № 5](README-lab5.md)
