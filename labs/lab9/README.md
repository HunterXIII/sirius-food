# Лабораторная работа № 9. Наблюдаемость «Сириус.Еды»

Цель работы — по одному идентификатору связать создание заказа, его оплату и обработку на кухне, а в Grafana посмотреть состояние системы в этот период. [Условие работы](task.md)

## План выполнения

1. Проверить запуск API, PostgreSQL, Redis, RabbitMQ, outbox и кухни.
2. Добавить middleware для `X-Correlation-ID`. Вернуть ID в ответе и сохранить его вместе с заказом.
3. Настроить JSON-логи в stdout. Перенести ID заказа в запись outbox и в заголовок сообщения RabbitMQ. Прочитать его на кухне и вывести вместе с номером заказа.
4. Открыть `/metrics` в API. Настроить сбор метрик FastAPI, RabbitMQ и Redis в Prometheus.
5. Подключить Prometheus к Grafana и собрать пять панелей для заказов, меню, ошибок, очереди кухни и кеша.
6. Создать и оплатить заказ с ID `demo-42`, сопоставить записи в логах и открыть соответствующий интервал в Grafana.
7. Вызвать контрольную ошибку и найти её стек и тег `correlation_id` в Sentry. Это проверка на 9 баллов.
8. Открыть Jaeger, найти единый трейс заказа и сравнить длительности спанов. Это проверка на 10 баллов.

## Запуск

Выполняйте команды из каталога проекта. Если файла `.env` ещё нет, скопируйте `.env.example` и задайте свой `SECRET_KEY`.

```bash
docker compose up -d --build
docker compose ps
curl -fsS http://127.0.0.1:8000/menu/items
```

- [Prometheus Targets](http://127.0.0.1:9090/targets) должен показывать `UP` для `sirius_app`, `rabbitmq` и `redis`.
- [Дашборд Grafana](http://127.0.0.1:3000/d/sirius-food-lab9/) загружается автоматически. При первом входе используйте `admin` / `admin` и задайте пароль по запросу Grafana.
- [Swagger](http://127.0.0.1:8000/docs) доступен при `DEBUG=True`.
- [Jaeger](http://127.0.0.1:16686) принимает трейсы заказов по OTLP внутри сети Docker.

## Проверка заказа

1. Зарегистрируйте студента в Swagger через `POST /users/register` и войдите через `POST /auth/login`. Сохраните `access_token` в переменную `TOKEN`, а номер пользователя — в `USER_ID`. Выберите доступное блюдо и запишите его ID в `ITEM_ID`. Для пустой учебной базы добавьте блюдо командой ниже.

   ```bash
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
   INSERT INTO menu_items (name, price, is_available)
   VALUES ('Борщ для ЛР 9', 100, true) RETURNING id;
   SQL
   ```

2. Создайте заказ. В выводе curl будет заголовок `x-correlation-id: demo-42`. Команда сохранит номер заказа в `ORDER_ID`.

   ```bash
   ORDER_ID=$(curl -fsS -D /dev/stderr http://127.0.0.1:8000/orders/create \
     -H "Authorization: Bearer $TOKEN" \
     -H 'X-Correlation-ID: demo-42' \
     -H 'Content-Type: application/json' \
     -d "{\"item_id\":$ITEM_ID,\"quantity\":1}" | jq -er .order_id)
   echo "$ORDER_ID"
   ```

3. Оплатите заказ. Если настроен тестовый магазин ЮKassa, используйте [сценарий тестовой оплаты](../README-payments.md). Для защиты в локальной учебной базе можно оплатить с внутреннего баланса через сервис из ЛР № 7. Операция выполняется только для указанного владельца заказа.

   ```bash
   curl -fsS -X POST "http://127.0.0.1:8000/users/$USER_ID/topup?amount=1000" \
     -H "Authorization: Bearer $TOKEN"

   docker compose exec -T api python - "$ORDER_ID" "$USER_ID" <<'PY'
   import sys

   from app.database import SessionLocal
   from app.models import User
   from app.modules.orders.repository import PostgresOrderRepository
   from app.modules.orders.service import OrderService

   order_id, user_id = map(int, sys.argv[1:])
   with SessionLocal() as db:
       student = db.get(User, user_id)
       order = OrderService(PostgresOrderRepository(db)).pay_order(order_id, student)
       print(f"Заказ {order.id}, статус {order.status}")
   PY
   ```

4. Найдите записи в API, outbox и на кухне. Флаг `-R` и `fromjson?` позволяют пропускать текстовые строки Uvicorn и других библиотек.

   ```bash
   docker compose logs --no-color --no-log-prefix --since 15m api outbox kitchen payments-worker \
     | jq -Rc 'fromjson? | select(.correlation_id == "demo-42")'
   ```

5. Сделайте несколько запросов к меню и создайте несколько учебных заказов в течение минуты. Откройте дашборд за последние 5 минут. По времени записи `order_created` найдите нужный участок графика запросов. После нескольких циклов сбора данных видны частота создания заказов, p95 меню, частота 5xx, число сообщений в `kitchen_queue` и доля попаданий Redis. Очередь может успеть опустеть между опросами, поэтому нулевая длина при обработанном заказе нормальна.

   ```bash
   curl -fsS http://127.0.0.1:8000/metrics | grep '^http_requests_total'
   ```

## Проверка Sentry

Создайте тестовый проект FastAPI в Sentry и скопируйте его DSN в `.env`. Установите `DEBUG=True` и `SENTRY_TEST_ENDPOINT_ENABLED=true`, затем пересоздайте API.

```bash
docker compose up -d api
curl -sS -o /dev/null -w '%{http_code}\n' -X POST \
  -H 'X-Correlation-ID: demo-42-sentry' \
  http://127.0.0.1:8000/_lab9/sentry-test
```

Команда вернёт `500`. В Sentry откройте **Issues**, выберите контрольную ошибку и покажите стек `RuntimeError` и тег `correlation_id=demo-42-sentry`. После показа выставьте `SENTRY_TEST_ENDPOINT_ENABLED=false` и снова выполните `docker compose up -d api`. Маршрут доступен только при включённых `DEBUG`, флаге проверки и заполненном DSN. [Интеграция Sentry с FastAPI](https://docs.sentry.io/platforms/python/integrations/fastapi/)

## Проверка Jaeger

Повторите [сценарий заказа](#проверка-заказа) после запуска Jaeger. В интерфейсе выберите сервис `sirius-api`, операцию `POST /orders/create`, в **Tags** укажите `correlation_id=demo-42` и нажмите **Find Traces**. Откройте свежий результат и сравните длительности спанов `POST /orders/create`, `OrderService.create`, `DB.insert_order`, `RabbitMQ.publish` и `Kitchen.consume`. У всех спанов должен быть один trace ID, а у `Kitchen.consume` родитель — `RabbitMQ.publish`.

Сохранённый в заказе `traceparent` связывает событие оплаты с исходным HTTP-запросом. Outbox передаёт в RabbitMQ контекст своего спана публикации, а кухня извлекает его при обработке сообщения. Jaeger хранит данные в памяти, поэтому после перезапуска создайте новый заказ для показа. [Передача контекста OpenTelemetry](https://opentelemetry.io/docs/languages/python/propagation/) · [Jaeger для локального запуска](https://www.jaegertracing.io/docs/1.76/getting-started/)

## Как работает код

- `app/core/correlation.py` берёт ID из запроса, генерирует UUID при пустом или неподходящем заголовке и сохраняет значение в `request.state`.
- `app/modules/orders/router.py` передаёт ID сервису заказов и пишет `order_created` сразу после успешного создания. Миграция добавляет поле `orders.correlation_id`, чтобы фоновая попытка оплаты или вебхук могли получить исходный ID. У старых заказов поле может быть пустым.
- Подтверждённая оплата сохраняет `OrderPaid` вместе со статусом заказа в одной транзакции. ID входит в payload записи outbox, поэтому переживает перезапуск воркера. `app/core/rabbitmq.py` переносит его в AMQP-заголовок `X-Correlation-ID`.
- `app/workers/consumer.py` читает AMQP-заголовок. После обработки сообщения кухня пишет `order_received` с `order_id`, `event_id` и `correlation_id`. При отмене через Saga ID берётся из того же заказа.
- Prometheus опрашивает контейнеры по именам сервисов каждые 5 секунд. RabbitMQ отдаёт метрики по каждой очереди, Redis exporter передаёт счётчики попаданий и промахов. Grafana автоматически загружает подготовленный дашборд из `observability/grafana`. [Метрики RabbitMQ](https://www.rabbitmq.com/docs/3.13/prometheus) · [Метрики FastAPI](https://pypi.org/project/prometheus-fastapi-instrumentator/7.0.0/)
- `app/core/sentry.py` подключает Sentry при заполненном DSN. Middleware добавляет `correlation_id` к событиям текущего запроса.
- `app/core/order_tracing.py` настраивает экспорт спанов заказов в Jaeger. У трейсов ассистента есть собственный экспорт в Phoenix.

## Результат проверочного запуска

На отдельном стенде заголовок ответа при создании заказа № 1 вернул `demo-42`. После оплаты из логов выбраны поля `service`, `message`, `order_id` и `correlation_id`.

```jsonl
{"service":"api","message":"order_created","order_id":1,"correlation_id":"demo-42"}
{"service":"outbox","message":"event_published","order_id":1,"correlation_id":"demo-42"}
{"service":"kitchen","message":"order_received","order_id":1,"correlation_id":"demo-42"}
```

Все три цели Prometheus были `UP`. Все пять запросов дашборда вернули значения. Пока кухня была остановлена, в очереди было одно сообщение. После запуска кухни очередь опустела. Ответы HTTP 503 дали ненулевую частоту 5xx в Prometheus.

Отдельно проверили оплату через подменённый шлюз ЮKassa. Вебхук пришёл без `X-Correlation-ID`, а в логах оплаты, outbox и кухни сохранился ID из запроса создания заказа. В Jaeger и этот заказ, и `demo-42` сохранились как единые трейсы. У `demo-42` было пять спанов. Самый длинный — `POST /orders/create` (73,60 мс).

Контрольный запрос вернул HTTP 500. Локальный приёмник Sentry получил `RuntimeError` с 30 кадрами стека и тегом `correlation_id=demo-42-sentry`. Для показа в облачном Sentry нужен DSN тестового проекта. Прошли 67 автотестов.

## Вопросы для защиты

- **Чем наблюдаемость отличается от мониторинга?** Мониторинг показывает состояние заранее выбранных показателей. Наблюдаемость помогает выяснить причину сбоя по данным системы, даже если такой сценарий заранее не предусмотрели.
- **Зачем нужен correlation ID?** По нему можно собрать записи об одном заказе из нескольких процессов и понять, на каком шаге цепочка остановилась.
- **Почему JSON пишется в stdout?** Docker собирает стандартный вывод, а JSON можно фильтровать по отдельным полям через `jq`.
- **Чем correlation ID отличается от trace ID?** Первый связывает шаги бизнес-операции, например создание и последующую оплату. Второй объединяет спаны одного распределённого трейса.
- **Что такое RED?** Rate — частота запросов, Errors — частота ошибок, Duration — длительность запросов. p95 оценивает время, в которое уложились 95% запросов.
- **Что такое span и trace?** Span — отдельная операция с временем начала и окончания. Trace объединяет связанные спаны.
- **Что такое context propagation?** Передача контекста через границы процессов. Для трейсов используется, например, заголовок `traceparent`, для нашей корреляции — `X-Correlation-ID`.
- **Чем Sentry отличается от логов?** Sentry группирует ошибки и показывает стек вызовов и контекст. Логи также фиксируют обычные успешные шаги.
- **Почему нельзя добавлять correlation ID в метки Prometheus?** Каждый новый ID создаст новые временные ряды. Из-за высокой кардинальности вырастут объём хранилища и стоимость запросов. В Grafana нужный интервал ищется по времени из логов.
- **Для чего нужны `request.state` и `call_next`?** `request.state` хранит ID на время текущего запроса. `call_next` передаёт запрос дальше и возвращает ответ, в который middleware добавляет заголовок.
