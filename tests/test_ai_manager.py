import threading
from types import SimpleNamespace
from unittest import TestCase

from bot.ai.errors import AIError
from bot.ai.manager import AIManager
from bot.ai.provider import AIAnswer


def make_config(**changes):
    values = dict(
        enabled=True, provider="gemini", cooldown_seconds=2.0, max_question_length=100,
        max_answer_length=1500, show_sources=True, chat_idle_minutes=30,
        max_concurrent_requests=3, gemini=SimpleNamespace(model="m"),
    )
    values.update(changes)
    return SimpleNamespace(**values)


class FakeProvider:
    title = "Gemini"

    def __init__(self):
        self.calls = []
        self.gate = None
        self.counter = 0

    def is_configured(self):
        return True

    def ask(self, question, conversation_id=None, keep_history=False):
        self.calls.append((question, conversation_id, keep_history))
        if self.gate is not None:
            self.gate.wait(5)
        self.counter += 1
        return AIAnswer("jawab " + question,
                        conversation_id="c%d" % self.counter if keep_history else None)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def user(id=1, name="budi"):
    return SimpleNamespace(id=id, username=name)


class ManagerTests(TestCase):
    def setUp(self):
        self.config = make_config()
        self.provider = FakeProvider()
        self.clock = Clock()
        self.manager = AIManager(lambda: self.config, lambda cfg: self.provider, self.clock)

    def ask(self, who, text="halo", **kw):
        return self.manager.ask(who, text, **kw)

    def kind(self, who, text="halo", **kw):
        with self.assertRaises(AIError) as caught:
            self.ask(who, text, **kw)
        return caught.exception.kind

    def test_a_question_is_answered_without_history(self):
        self.assertEqual(self.ask(user()).text, "jawab halo")
        self.assertEqual(self.provider.calls, [("halo", None, False)])

    def test_disabled_empty_and_too_long(self):
        self.assertEqual(self.kind(user(), "   "), "empty_question")
        self.assertEqual(self.kind(user(), "x" * 101), "too_long")
        self.config.enabled = False
        self.assertEqual(self.kind(user()), "disabled")

    def test_cooldown_counts_from_the_end_of_the_last_answer(self):
        self.ask(user())
        self.clock.now += 1
        with self.assertRaises(AIError) as caught:
            self.ask(user())
        self.assertEqual(caught.exception.kind, "cooldown")
        self.assertAlmostEqual(caught.exception.retry_after, 1.0)
        self.clock.now += 1.5
        self.ask(user())
        self.ask(user(2, "ani"))  # someone else is not held up

    def test_a_chat_continues_the_conversation(self):
        who = user()
        self.manager.start_chat(who)
        self.assertTrue(self.manager.is_chatting(who))
        self.ask(who, "satu", chat=True)
        self.clock.now += 5
        self.ask(who, "dua", chat=True)
        self.assertEqual(self.provider.calls[0], ("satu", None, True))
        self.assertEqual(self.provider.calls[1], ("dua", "c1", True))

    def test_clear_forgets_and_end_stops_the_chat(self):
        who = user()
        self.manager.start_chat(who)
        self.ask(who, "satu", chat=True)
        self.manager.clear_chat(who)
        self.assertTrue(self.manager.is_chatting(who))
        self.clock.now += 5
        self.ask(who, "dua", chat=True)
        self.assertEqual(self.provider.calls[1], ("dua", None, True))
        self.assertTrue(self.manager.end_chat(who))
        self.assertFalse(self.manager.is_chatting(who))
        self.assertFalse(self.manager.end_chat(who))

    def test_a_chat_ends_by_itself_when_idle(self):
        who = user()
        self.manager.start_chat(who)
        self.clock.now += 31 * 60
        self.assertFalse(self.manager.is_chatting(who))

    def test_idle_timeout_can_be_switched_off(self):
        self.config.chat_idle_minutes = 0
        who = user()
        self.manager.start_chat(who)
        self.clock.now += 100 * 3600
        self.assertTrue(self.manager.is_chatting(who))

    def test_a_reused_user_id_does_not_inherit_a_chat(self):
        self.manager.start_chat(user(5, "budi"))
        self.assertFalse(self.manager.is_chatting(user(5, "ani")))

    def test_questions_of_one_user_do_not_overlap_and_the_bot_has_a_limit(self):
        self.config.max_concurrent_requests = 1
        self.manager = AIManager(lambda: self.config, lambda cfg: self.provider, self.clock)
        self.provider.gate = threading.Event()
        started = threading.Event()
        results = []

        def slow():
            started.set()
            results.append(self.ask(user(1)))

        thread = threading.Thread(target=slow)
        thread.start()
        started.wait(2)
        for _ in range(100):  # wait until the provider is really busy
            if self.provider.calls:
                break
            threading.Event().wait(0.01)
        self.assertEqual(self.kind(user(1)), "user_busy")
        self.assertEqual(self.kind(user(2, "ani")), "busy_global")
        self.provider.gate.set()
        thread.join(5)
        self.assertEqual(len(results), 1)

    def test_on_start_runs_only_for_accepted_questions(self):
        seen = []
        self.ask(user(), on_start=lambda: seen.append("start"))
        self.assertEqual(seen, ["start"])
        with self.assertRaises(AIError):
            self.ask(user(), on_start=lambda: seen.append("again"))  # cooldown
        self.assertEqual(seen, ["start"])

    def test_check_ready(self):
        self.manager.check_ready()
        self.config.enabled = False
        with self.assertRaises(AIError):
            self.manager.check_ready()
