import importlib
from unittest import TestCase

# bot.TeamTalk loads the TeamTalk SDK library, which is not needed to test split().
try:
    split = importlib.import_module("bot.TeamTalk").split
except Exception:  # pragma: no cover - depends on the machine
    split = None


class SplitTests(TestCase):
    def setUp(self):
        if split is None:
            self.skipTest("the TeamTalk SDK cannot be loaded here")

    def test_a_short_text_is_one_message(self):
        self.assertEqual(split("halo"), ["halo"])

    def test_a_long_single_paragraph_is_not_lost(self):
        # The former version dropped every word of such a line and sent empty
        # messages, so a long answer of the AI vanished.
        text = "Cuaca di Blora hari ini cerah berawan dengan suhu sekitar 33 derajat. " * 8
        parts = split(text)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(0 < len(part) <= 256 for part in parts))
        self.assertEqual(" ".join(parts).split(), text.split())

    def test_lines_are_kept_together_while_they_fit(self):
        text = "\n".join(["baris %d" % i for i in range(100)])
        parts = split(text)
        self.assertTrue(all(len(part) <= 256 for part in parts))
        self.assertEqual("\n".join(parts), text)

    def test_a_word_longer_than_a_message_is_cut(self):
        parts = split("a " + "x" * 600 + " b")
        self.assertTrue(all(len(part) <= 256 for part in parts))
        self.assertEqual("".join(parts).replace("\n", "").replace(" ", ""), "a" + "x" * 600 + "b")

    def test_no_empty_messages(self):
        self.assertNotIn("", split("x" * 700 + "\n" + "y" * 700))
