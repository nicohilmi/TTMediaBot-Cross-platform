import glob
import os
import re
from unittest import TestCase, skipUnless

try:
    from babel.messages.mofile import read_mo
    from babel.messages.pofile import read_po
except ImportError:  # babel is listed in requirements.txt
    read_po = None

LOCALE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "locale")


def placeholders(text):
    return set(re.findall(r"\{[^{}]*\}", text))


def po_files():
    return sorted(glob.glob(os.path.join(LOCALE_DIR, "*", "LC_MESSAGES", "TTMediaBot.po")))


def load_po(path):
    code = path.split(os.sep)[-3]
    with open(path, "rb") as f:
        return code, read_po(f, locale=code)


@skipUnless(read_po, "babel is not installed")
class LocaleTests(TestCase):
    def test_a_translation_keeps_the_placeholders_of_its_source(self):
        # A translation that renames or drops a {placeholder} breaks the command
        # ({mode} against {modes}) or hides what it was meant to show ({}).
        problems = []
        for path in po_files():
            code, catalog = load_po(path)
            for message in catalog:
                if not message.id or message.fuzzy or not message.string:
                    continue
                if isinstance(message.string, (list, tuple)):
                    continue
                if placeholders(message.id) != placeholders(message.string):
                    problems.append("{}: {!r}".format(code, message.id[:60]))
        self.assertEqual(problems, [])

    def test_compiled_files_are_up_to_date_with_the_sources(self):
        # Run  python tools/compile_locales.py  after editing a .po file.
        stale = []
        for path in po_files():
            code, catalog = load_po(path)
            with open(path[:-3] + ".mo", "rb") as f:
                compiled = read_mo(f)
            for message in catalog:
                if not message.id or message.fuzzy or not message.string:
                    continue
                if isinstance(message.string, (list, tuple)):
                    continue
                built = compiled.get(message.id)
                if built is None or built.string != message.string:
                    stale.append("{}: {!r}".format(code, message.id[:60]))
        self.assertEqual(stale, [])

    def test_indonesian_is_complete(self):
        path = os.path.join(LOCALE_DIR, "id", "LC_MESSAGES", "TTMediaBot.po")
        _, catalog = load_po(path)
        missing = [m.id[:60] for m in catalog if m.id and (not m.string or m.fuzzy)]
        self.assertEqual(missing, [])
