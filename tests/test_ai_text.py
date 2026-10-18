from unittest import TestCase

from bot.ai.text import shorten, to_plain_text


class PlainTextTests(TestCase):
    def test_markdown_symbols_are_removed(self):
        text = "**Cuaca** hari ini:\n* cerah\n* *berawan* sore hari\n\n## Saran\nBawa `payung`."
        self.assertEqual(
            to_plain_text(text),
            "Cuaca hari ini:\n- cerah\n- berawan sore hari\n\nSaran\nBawa payung.",
        )

    def test_code_fences_keep_their_content(self):
        self.assertEqual(to_plain_text("Coba:\n```python\nprint(1)\n```\nSelesai"),
                         "Coba:\nprint(1)\nSelesai")

    def test_links_keep_their_address(self):
        self.assertEqual(to_plain_text("Lihat [situs ini](https://example.com/a)."),
                         "Lihat situs ini (https://example.com/a).")
        self.assertEqual(to_plain_text("[https://a.io](https://a.io)"), "https://a.io")

    def test_snake_case_and_urls_with_underscores_are_not_damaged(self):
        text = "Pakai nama_variabel_ini di https://example.com/a_b_c ya"
        self.assertEqual(to_plain_text(text), text)

    def test_multiplication_is_not_italic(self):
        self.assertEqual(to_plain_text("2 * 3 * 4 = 24"), "2 * 3 * 4 = 24")

    def test_blank_lines_are_collapsed_and_ends_trimmed(self):
        self.assertEqual(to_plain_text("\n\nsatu \n\n\n\ndua \n\n"), "satu\n\ndua")


class ShortenTests(TestCase):
    def test_short_text_and_no_limit_are_unchanged(self):
        self.assertEqual(shorten("pendek", 100), "pendek")
        self.assertEqual(shorten("x" * 5000, 0), "x" * 5000)

    def test_long_text_is_cut_at_a_sentence_end(self):
        text = "Kalimat pertama selesai. Kalimat kedua juga selesai. Kalimat ketiga panjang sekali."
        out = shorten(text, 60)
        self.assertLessEqual(len(out), 60)
        self.assertTrue(out.endswith("..."))
        self.assertIn("Kalimat kedua juga selesai.", out)

    def test_a_text_without_spaces_is_still_cut(self):
        out = shorten("x" * 300, 50)
        self.assertEqual(len(out), 50)
        self.assertTrue(out.endswith("..."))
