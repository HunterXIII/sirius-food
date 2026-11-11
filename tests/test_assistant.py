import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx

from app.modules.assistant.openrouter import OpenRouterClient
from app.modules.assistant.repository import AssistantRepository, ConversationTurn, Source
from app.modules.assistant.service import AssistantService


class AssistantTest(unittest.TestCase):
    def setUp(self):
        self.repository = Mock()
        self.service = AssistantService(self.repository, OpenRouterClient("test-key", "test-model:free"))

    @patch("app.modules.assistant.openrouter.httpx.post")
    def test_faq_uses_retrieved_context(self, post):
        self.repository.find_sources.return_value = [
            Source("faq:cancel", "Отмена", "Неоплаченный заказ можно отменить."),
        ]
        post.return_value.json.return_value = {
            "choices": [{"message": {"content": "Неоплаченный заказ можно отменить."}}],
        }

        chat_id, reply_id, answer = self.service.chat("Когда можно отменить заказ?", 1, None)

        self.assertEqual(answer.mode, "rag")
        request = post.call_args.kwargs["json"]
        self.assertEqual(request["model"], "test-model:free")
        self.assertIn(answer.text, request["messages"][1]["content"])
        self.repository.save_reply.assert_called_once_with(
            reply_id,
            1,
            chat_id=chat_id,
            new_chat=True,
            message="Когда можно отменить заказ?",
            answer=answer.text,
            mode="rag",
            sources=answer.sources,
        )

    @patch("app.modules.assistant.openrouter.httpx.post")
    def test_fallback_on_rate_limit(self, post):
        self.repository.find_sources.return_value = [Source("menu:1", "Борщ", "Цена 180 ₽.")]
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        post.return_value = httpx.Response(429, request=request)

        _, _, answer = self.service.chat("Сколько стоит борщ?", 1, None)

        self.assertEqual(answer.mode, "fallback")
        self.assertEqual(answer.sources[0].key, "menu:1")

    def test_order_status_uses_user_and_order_id(self):
        self.repository.get_order_details.return_value = SimpleNamespace(
            id=5, status="paid", delivery_status="in_progress",
        )

        _, _, answer = self.service.chat("Где мой заказ №5?", 2, None)

        self.assertEqual(answer.text, "Заказ №5 в доставке.")
        self.repository.get_order_details.assert_called_once_with(2, 5)
        self.repository.find_sources.assert_not_called()

    def test_order_contents_for_explicit_and_latest_order(self):
        self.repository.get_order_details.return_value = SimpleNamespace(
            id=64, status="processing", dish_name="Борщ", quantity=2,
        )

        for message, order_id in (
            ("что находиться в моём заказе?", 64),
            ("Что в моём заказе?", None),
        ):
            with self.subTest(message=message):
                _, _, answer = self.service.chat(message, 2, order_id)

                self.assertEqual(answer.text, "В заказе №64 — «Борщ», 2 шт.")
                self.assertEqual(answer.mode, "order")
                self.repository.get_order_details.assert_called_with(2, order_id)
        self.repository.find_sources.assert_not_called()


    @patch("app.modules.assistant.openrouter.httpx.post")
    def test_followup_uses_chat_context_and_fresh_sources(self, post):
        self.repository.owns_chat.return_value = True
        self.repository.recent_context.return_value = [
            ConversationTurn("Что порекомендуешь?", "Борщ за 180 ₽."),
        ]
        self.repository.find_sources.return_value = [Source("menu:1", "Борщ", "Цена 220 ₽.")]
        post.return_value.json.return_value = {
            "choices": [{"message": {"content": "Борщ стоит 220 ₽."}}],
        }

        chat_id, _, answer = self.service.chat("А сколько он стоит?", 1, None, "my-chat")

        self.assertEqual(chat_id, "my-chat")
        self.assertEqual(answer.text, "Борщ стоит 220 ₽.")
        self.repository.recent_context.assert_called_once_with(1, "my-chat")
        question, _, contextual_question = self.repository.find_sources.call_args.args
        self.assertEqual(question, "А сколько он стоит?")
        self.assertIn("Борщ", contextual_question)
        body = json.loads(post.call_args.kwargs["json"]["messages"][1]["content"])
        self.assertEqual(body["history"][0]["message"], "Что порекомендуешь?")
        self.assertEqual(body["sources"][0]["facts"], "Цена 220 ₽.")


    def test_dish_named_in_question_takes_priority_over_chat_history(self):
        db = Mock()
        db.execute.return_value.all.return_value = [
            (SimpleNamespace(id=1, name="Борщ", price=100, is_available=True), "Супы"),
            (SimpleNamespace(id=2, name="Булочка", price=240, is_available=True), "Выпечка"),
        ]
        embed = Mock()

        sources = AssistantRepository(db).find_sources(
            "а БОРЩ есть?", embed, "Какая есть выпечка? Булочка и кекс.",
        )

        self.assertEqual(sources, [Source("menu:1", "Борщ — Супы", "Цена 100 ₽. В наличии.")])
        embed.assert_not_called()
