import threading
import time
from types import SimpleNamespace
from unittest import TestCase

from bot.ai.errors import AIError
from bot.ai.gemini import GeminiProvider, build_instruction, classify_error


def settings(**changes):
    values = dict(
        api_key="key", model="gemini-test", google_search=True, thinking_level="low",
        timeout_seconds=5.0, max_retries=2, system_instruction="",
    )
    values.update(changes)
    return SimpleNamespace(**values)


class HttpError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def interaction(text="Jawaban", id="int_1", steps=None):
    return SimpleNamespace(output_text=text, id=id, steps=steps or [])


def grounded():
    return [
        SimpleNamespace(type="google_search_call"),
        SimpleNamespace(type="model_output", content=[SimpleNamespace(
            type="text", text="Cerah.",
            annotations=[
                SimpleNamespace(type="url_citation", url="https://bmkg.go.id/x", title="bmkg.go.id"),
                SimpleNamespace(type="url_citation", uri="https://detik.com/y", title="detik.com"),
                SimpleNamespace(type="url_citation", url="https://bmkg.go.id/z", title="bmkg.go.id"),
            ],
        )]),
    ]


class FakeClient:
    """Stands in for google.genai.Client: answers from a script of results."""

    def __init__(self, *results):
        self.results = list(results)
        self.requests = []
        self.interactions = SimpleNamespace(create=self.create)

    def create(self, **request):
        self.requests.append(request)
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        if callable(result):
            return result()
        return result


def provider(client, **changes):
    sleeps = []
    instance = GeminiProvider(settings(**changes), client_factory=lambda cfg: client,
                              sleep=sleeps.append)
    instance.sleeps = sleeps
    return instance


class RequestTests(TestCase):
    def test_a_single_question_is_not_stored_and_uses_google_search(self):
        client = FakeClient(interaction())
        answer = provider(client).ask("bagaimana cuaca di blora saat ini")
        request = client.requests[0]
        self.assertEqual(request["model"], "gemini-test")
        self.assertEqual(request["input"], "bagaimana cuaca di blora saat ini")
        self.assertEqual(request["tools"], [{"type": "google_search"}])
        self.assertEqual(request["generation_config"], {"thinking_level": "low"})
        self.assertIs(request["store"], False)
        self.assertNotIn("previous_interaction_id", request)
        self.assertIn("Current date and time", request["system_instruction"])
        self.assertEqual(answer.text, "Jawaban")
        self.assertIsNone(answer.conversation_id)

    def test_a_chat_is_stored_and_continued(self):
        client = FakeClient(interaction(id="int_1"), interaction(id="int_2"))
        ai = provider(client)
        first = ai.ask("halo", keep_history=True)
        second = ai.ask("lanjut", conversation_id=first.conversation_id, keep_history=True)
        self.assertEqual(first.conversation_id, "int_1")
        self.assertIs(client.requests[0]["store"], True)
        self.assertEqual(client.requests[1]["previous_interaction_id"], "int_1")
        self.assertEqual(second.conversation_id, "int_2")

    def test_search_and_thinking_can_be_switched_off(self):
        client = FakeClient(interaction())
        provider(client, google_search=False, thinking_level="").ask("halo")
        self.assertNotIn("tools", client.requests[0])
        self.assertNotIn("generation_config", client.requests[0])

    def test_own_instruction_replaces_the_built_in_one(self):
        text = build_instruction("Jawab seperti bajak laut.")
        self.assertTrue(text.startswith("Jawab seperti bajak laut."))
        self.assertNotIn("TeamTalk", text)

    def test_sources_are_named_once_each(self):
        client = FakeClient(interaction(text="Cerah.", steps=grounded()))
        answer = provider(client).ask("cuaca")
        self.assertEqual([title for title, _ in answer.sources], ["bmkg.go.id", "detik.com"])
        self.assertTrue(answer.searched)

    def test_the_answer_is_read_from_the_steps_when_there_is_no_output_text(self):
        client = FakeClient(SimpleNamespace(output_text=None, id="x", steps=grounded()))
        self.assertEqual(provider(client).ask("cuaca").text, "Cerah.")

    def test_an_empty_answer_is_an_error(self):
        with self.assertRaises(AIError) as caught:
            provider(FakeClient(interaction(text="  "))).ask("halo")
        self.assertEqual(caught.exception.kind, "empty")

    def test_the_key_can_come_from_the_environment(self):
        import os
        old = os.environ.pop("GEMINI_API_KEY", None)
        try:
            ai = GeminiProvider(settings(api_key=""))
            self.assertFalse(ai.is_configured())
            os.environ["GEMINI_API_KEY"] = "from-env"
            self.assertTrue(ai.is_configured())
        finally:
            os.environ.pop("GEMINI_API_KEY", None)
            if old is not None:
                os.environ["GEMINI_API_KEY"] = old

    def test_without_a_key_nothing_is_sent(self):
        import os
        saved = {k: os.environ.pop(k) for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY") if k in os.environ}
        try:
            with self.assertRaises(AIError) as caught:
                GeminiProvider(settings(api_key="")).ask("halo")
        finally:
            os.environ.update(saved)
        self.assertEqual(caught.exception.kind, "not_configured")


class ErrorTests(TestCase):
    def test_busy_servers_are_retried_with_a_growing_pause(self):
        client = FakeClient(HttpError(503, "UNAVAILABLE overloaded"),
                            HttpError(500, "INTERNAL"), interaction())
        ai = provider(client)
        self.assertEqual(ai.ask("halo").text, "Jawaban")
        self.assertEqual(len(client.requests), 3)
        self.assertEqual(ai.sleeps, [1.0, 2.0])

    def test_retries_stop_at_the_limit(self):
        client = FakeClient(*[HttpError(503, "UNAVAILABLE")] * 5)
        with self.assertRaises(AIError) as caught:
            provider(client, max_retries=1).ask("halo")
        self.assertEqual(caught.exception.kind, "server")
        self.assertEqual(len(client.requests), 2)

    def test_a_wrong_key_is_not_retried(self):
        client = FakeClient(HttpError(400, "API key not valid. Please pass a valid API key."))
        with self.assertRaises(AIError) as caught:
            provider(client).ask("halo")
        self.assertEqual(caught.exception.kind, "auth")
        self.assertEqual(len(client.requests), 1)

    def test_a_daily_quota_is_final_but_a_per_minute_limit_is_retried(self):
        daily = FakeClient(HttpError(429, "You exceeded your current quota, please check your plan and billing details"))
        with self.assertRaises(AIError) as caught:
            provider(daily).ask("halo")
        self.assertEqual(caught.exception.kind, "quota")
        self.assertEqual(len(daily.requests), 1)
        minute = FakeClient(HttpError(429, "RESOURCE_EXHAUSTED quota. Please retry in 24s"), interaction())
        self.assertEqual(provider(minute).ask("halo").text, "Jawaban")

    def test_an_unknown_model_is_reported(self):
        client = FakeClient(HttpError(404, "models/gemini-old is not found for API version"))
        with self.assertRaises(AIError) as caught:
            provider(client).ask("halo")
        self.assertEqual(caught.exception.kind, "model")

    def test_a_rejected_thinking_level_is_dropped_and_the_question_repeated(self):
        client = FakeClient(HttpError(400, "Thinking level MINIMAL is not supported for this model."),
                            interaction())
        with self.assertLogs(level="WARNING"):
            self.assertEqual(provider(client).ask("halo").text, "Jawaban")
        self.assertIn("generation_config", client.requests[0])
        self.assertNotIn("generation_config", client.requests[1])

    def test_a_lost_conversation_starts_a_new_one(self):
        client = FakeClient(HttpError(404, "Interaction int_old not found"), interaction(id="int_new"))
        answer = provider(client).ask("lanjut", conversation_id="int_old", keep_history=True)
        self.assertNotIn("previous_interaction_id", client.requests[1])
        self.assertTrue(answer.conversation_reset)
        self.assertEqual(answer.conversation_id, "int_new")

    def test_a_network_failure_is_retried_then_reported(self):
        client = FakeClient(*[ConnectionError("getaddrinfo failed")] * 3)
        with self.assertRaises(AIError) as caught:
            provider(client).ask("halo")
        self.assertEqual(caught.exception.kind, "network")

    def test_a_slow_answer_is_given_up(self):
        release = threading.Event()
        client = FakeClient(lambda: release.wait(5) and interaction(),
                            lambda: release.wait(5) and interaction())
        started = time.monotonic()
        try:
            with self.assertRaises(AIError) as caught:
                provider(client, timeout_seconds=0.2, max_retries=1).ask("halo")
        finally:
            release.set()
        self.assertEqual(caught.exception.kind, "timeout")
        self.assertLess(time.monotonic() - started, 3)


class ClassifyTests(TestCase):
    def test_region_and_server_errors(self):
        self.assertEqual(classify_error(HttpError(400, "User location is not supported for the API use.")),
                         ("region", False))
        self.assertEqual(classify_error(HttpError(502, "bad gateway")), ("server", True))
        self.assertEqual(classify_error(ValueError("boom"))[0], "unknown")
