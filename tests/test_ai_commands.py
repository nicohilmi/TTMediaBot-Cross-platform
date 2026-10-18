from types import SimpleNamespace
from unittest import TestCase
from unittest import mock

from bot import errors
from bot.ai.errors import AIError
from bot.ai.manager import AIManager
from bot.ai.provider import AIAnswer
from bot.commands import CommandProcessor, user_commands
from bot.commands.command import Command


class FakeProvider:
    title = "Gemini"

    def __init__(self):
        self.calls = []
        self.error = None
        self.configured = True

    def is_configured(self):
        return self.configured

    def ask(self, question, conversation_id=None, keep_history=False):
        self.calls.append((question, conversation_id, keep_history))
        if self.error:
            raise self.error
        return AIAnswer(
            "**Cerah** hari ini",
            sources=[("bmkg.go.id", "u"), ("detik.com", "v"), ("kompas.com", "w"), ("x.com", "x")],
            conversation_id="c%d" % len(self.calls) if keep_history else None,
        )


class FakeTT:
    def __init__(self):
        self.channel = SimpleNamespace(id=1)
        self.sent = []

    def send_message(self, text, user=None, type=1):
        self.sent.append(text)


def make_ai_config(**changes):
    values = dict(
        enabled=True, provider="gemini", cooldown_seconds=0.0, max_question_length=2000,
        max_answer_length=1500, show_sources=True, chat_idle_minutes=30,
        max_concurrent_requests=3, gemini=SimpleNamespace(model="gemini-test"),
    )
    values.update(changes)
    return SimpleNamespace(**values)


def make_user(id=3, name="budi", channel=1):
    return SimpleNamespace(
        id=id, username=name, nickname=name.title(), is_admin=False, type=None,
        client_name="TeamTalk 5", is_banned=False, channel=SimpleNamespace(id=channel),
    )


class AITestCase(TestCase):
    def setUp(self):
        self.provider = FakeProvider()
        self.ai_config = make_ai_config()
        self.tt = FakeTT()
        self.thinking = []
        self.bot = SimpleNamespace(
            config=SimpleNamespace(
                ai=self.ai_config,
                general=SimpleNamespace(blocked_commands=[], send_channel_messages=True),
            ),
            ttclient=self.tt,
            translator=SimpleNamespace(translate=lambda text: text),
        )
        self.bot.ai_manager = AIManager(lambda: self.ai_config, lambda cfg: self.provider)
        for name in ("cache", "cache_manager", "module_manager", "player",
                     "service_manager", "config_manager"):
            setattr(self.bot, name, None)
        patcher = mock.patch.object(
            Command, "send_message_async",
            lambda command, text, *args, **kwargs: self.thinking.append(text),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def command(self, cls):
        processor = SimpleNamespace(
            bot=self.bot, cache=None, cache_manager=None, config=self.bot.config,
            config_manager=None, module_manager=None, player=None, service_manager=None,
            task_processor=None, ttclient=self.tt, translator=self.bot.translator,
        )
        return cls(processor)


class AICommandTests(AITestCase):
    def test_the_answer_is_plain_text_with_its_sources(self):
        reply = self.command(user_commands.AICommand)("cuaca blora", make_user())
        self.assertEqual(reply, "Cerah hari ini\nSources: bmkg.go.id, detik.com, kompas.com")
        self.assertEqual(self.thinking, ["AI is thinking..."])
        self.assertEqual(self.provider.calls, [("cuaca blora", None, False)])

    def test_sources_can_be_switched_off(self):
        self.ai_config.show_sources = False
        reply = self.command(user_commands.AICommand)("cuaca", make_user())
        self.assertEqual(reply, "Cerah hari ini")

    def test_a_long_answer_is_cut(self):
        self.ai_config.max_answer_length = 8
        self.ai_config.show_sources = False
        reply = self.command(user_commands.AICommand)("cuaca", make_user())
        self.assertLessEqual(len(reply), 8)
        self.assertTrue(reply.endswith("..."))

    def test_no_question_shows_the_help(self):
        with self.assertRaises(errors.InvalidArgumentError):
            self.command(user_commands.AICommand)("   ", make_user())
        self.assertEqual(self.thinking, [])

    def test_every_error_has_a_message_without_leftover_placeholders(self):
        kinds = ["disabled", "not_configured", "sdk_missing", "unknown_provider", "too_long",
                 "cooldown", "user_busy", "busy_global", "auth", "region", "quota", "server",
                 "timeout", "network", "model", "empty", "rejected", "unknown"]
        for kind in kinds:
            error = AIError(kind, "5", retry_after=1.2)
            text = user_commands.ai_error_text(lambda t: t, error, "gemini-test")
            self.assertTrue(text, kind)
            self.assertNotIn("{", text, kind)
        self.assertIn("5 characters", user_commands.ai_error_text(lambda t: t, AIError("too_long", "5")))
        self.assertIn("2 seconds", user_commands.ai_error_text(
            lambda t: t, AIError("cooldown", retry_after=1.2)))

    def test_a_failure_is_reported_in_words(self):
        self.provider.error = AIError("quota")
        reply = self.command(user_commands.AICommand)("cuaca", make_user())
        self.assertEqual(reply, "The usage limit of the AI was reached. Please try again later")

    def test_a_lost_conversation_is_mentioned(self):
        user = make_user()
        self.bot.ai_manager.start_chat(user)
        original = self.provider.ask

        def reset(question, conversation_id=None, keep_history=False):
            answer = original(question, conversation_id, keep_history)
            answer.conversation_reset = True
            return answer

        self.provider.ask = reset
        reply = self.command(user_commands.AIChatMessageCommand)("lanjut", user)
        self.assertTrue(reply.startswith("The previous conversation was no longer available"))


class ChatCommandTests(AITestCase):
    def test_chat_starts_a_conversation_and_greets(self):
        user = make_user()
        reply = self.command(user_commands.ChatCommand)("", user)
        self.assertTrue(reply.startswith("Welcome to Gemini chat!"))
        self.assertIn("/clear", reply)
        self.assertIn("/c -", reply)
        self.assertTrue(self.bot.ai_manager.is_chatting(user))
        self.assertEqual(self.provider.calls, [])

    def test_chat_with_a_question_answers_it_straight_away(self):
        user = make_user()
        reply = self.command(user_commands.ChatCommand)("halo", user)
        self.assertTrue(reply.startswith("Cerah hari ini"))
        self.assertTrue(self.bot.ai_manager.is_chatting(user))
        self.assertEqual(self.provider.calls, [("halo", None, True)])

    def test_chat_does_not_start_when_the_ai_cannot_work(self):
        user = make_user()
        self.provider.configured = False
        reply = self.command(user_commands.ChatCommand)("", user)
        self.assertIn("not set up yet", reply)
        self.assertFalse(self.bot.ai_manager.is_chatting(user))
        self.ai_config.enabled = False
        self.assertEqual(self.command(user_commands.ChatCommand)("", user), "The AI is turned off")

    def test_the_commands_inside_a_chat(self):
        user = make_user()
        chat = self.command(user_commands.AIChatMessageCommand)
        self.bot.ai_manager.start_chat(user)
        chat("satu", user)
        self.assertEqual(chat("/clear", user), "Conversation cleared. You can start a new topic")
        chat("dua", user)
        self.assertEqual(self.provider.calls[1], ("dua", None, True))
        self.assertTrue(chat("/chat", user).startswith("Welcome to Gemini chat!"))
        self.assertEqual(chat("/C", user), "Chat ended")
        self.assertFalse(self.bot.ai_manager.is_chatting(user))


class RoutingTests(AITestCase):
    def setUp(self):
        super().setUp()
        self.processor = CommandProcessor(self.bot)

    def send(self, text, user):
        self.processor._run(SimpleNamespace(text=text, user=user))
        return self.tt.sent[-1] if self.tt.sent else None

    def test_ai_is_a_command_and_chat_routes_every_message(self):
        user = make_user()
        self.assertTrue(self.send("ai cuaca blora", user).startswith("Cerah hari ini"))
        self.assertEqual(self.provider.calls[-1], ("cuaca blora", None, False))
        self.assertTrue(self.send("/chat", user).startswith("Welcome to Gemini chat!"))
        # Inside the chat a word like "p" is no command: it is a message to the AI.
        self.assertTrue(self.send("p lagu santai", user).startswith("Cerah hari ini"))
        self.assertEqual(self.provider.calls[-1], ("p lagu santai", None, True))
        self.send("dan kemarin?", user)  # the second message continues the conversation
        self.assertEqual(self.provider.calls[-1], ("dan kemarin?", "c2", True))
        self.assertEqual(self.send("/c", user), "Chat ended")
        self.assertEqual(self.send("halo", user), 'Unknown command. Send "h" for help.')

    def test_only_the_user_in_the_chat_is_routed(self):
        self.send("chat", make_user(3, "budi"))
        self.send("halo", make_user(4, "ani"))
        self.assertEqual(self.tt.sent[-1], 'Unknown command. Send "h" for help.')

    def test_leaving_the_channel_ends_the_chat(self):
        user = make_user()
        self.send("chat", user)
        away = make_user(channel=9)
        self.assertEqual(self.send("halo", away), "You are not in bot's channel")
        self.assertFalse(self.bot.ai_manager.is_chatting(user))

    def test_the_commands_can_be_blocked_by_an_admin(self):
        self.bot.config.general.blocked_commands.append("ai")
        self.assertEqual(self.send("ai halo", make_user()), "This command is blocked")

    def test_both_commands_are_listed_in_the_help(self):
        self.assertIn("ai", self.processor.commands_dict)
        self.assertIn("chat", self.processor.commands_dict)
        text = self.processor.help("ai", make_user())
        self.assertTrue(text.startswith("ai QUESTION"))
