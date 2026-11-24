import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest
from pact import Pact, Verifier, match
from pact.types import Message

from app import models
from app.core.events import order_paid
from app.workers import consumer

CONSUMER = "Kitchen"
PROVIDER = "SiriusFood"
ROUTING_KEY = "order.paid"
ORDER_ID = 42
CUSTOMER_ID = 7
AMOUNT = 350.50


@pytest.fixture
def order_paid_contract(tmp_path, monkeypatch):
    pact = Pact(CONSUMER, PROVIDER).with_specification("V4")
    pact.upon_receiving("OrderPaid", "Async").with_body(
        {
            "event_id": match.regex(
                "123e4567-e89b-12d3-a456-426614174000",
                regex=r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$",
            ),
            "order_id": match.int(ORDER_ID),
            "customer_id": match.int(CUSTOMER_ID),
            "amount": match.decimal(AMOUNT),
        },
        content_type="application/json",
    ).with_metadata({"routing_key": ROUTING_KEY})

    save_event = Mock(return_value="Принят заказ")
    monkeypatch.setattr(consumer, "save_event", save_event)

    def consume(body, metadata):
        message = Mock(body=body, headers={}, routing_key=metadata["routing_key"])
        message.process.return_value = AsyncMock()
        asyncio.run(consumer.process_message(message, "kitchen"))
        message.process.assert_called_once_with(requeue=False)
        save_event.assert_called_once()
        event, service, routing_key = save_event.call_args.args
        assert (service, routing_key) == ("kitchen", ROUTING_KEY)
        assert (event.order_id, event.customer_id, event.amount) == (ORDER_ID, CUSTOMER_ID, AMOUNT)

    pact.verify(consume, "Async")
    pact.write_file(tmp_path)
    return tmp_path / f"{CONSUMER}-{PROVIDER}.json"


def provider_message() -> Message:
    # Как при оплате, событие строит код монолита. Outbox хранит этот payload.
    event = models.OutboxEvent(
        routing_key=ROUTING_KEY, payload=order_paid(ORDER_ID, CUSTOMER_ID, AMOUNT)
    )
    return {
        "contents": json.dumps(event.payload).encode(),
        "content_type": "application/json",
        "metadata": {"routing_key": event.routing_key},
    }


def provider_verifier(contract, message):
    return Verifier(PROVIDER).message_handler({"OrderPaid": message}).add_source(contract)


def test_monolith_matches_kitchen_contract(order_paid_contract):
    provider_verifier(order_paid_contract, provider_message()).verify()


def test_pact_rejects_amount_renamed_to_total(order_paid_contract):
    incompatible = provider_message()
    payload = json.loads(incompatible["contents"])
    payload["total"] = payload.pop("amount")
    incompatible["contents"] = json.dumps(payload).encode()

    verifier = provider_verifier(order_paid_contract, incompatible)
    with pytest.raises(RuntimeError, match="Failed to execute verifier"):
        verifier.verify()
    assert "missing the following keys: amount" in verifier.output(strip_ansi=True)
