"""Guards for running on Python 3.10 up to 3.15.

Python 3.15 made UTF-8 the default text encoding (PEP 686), added lazy imports
(PEP 810) and removes APIs that were deprecated for years. Most of what is checked
here is read from the source with the ``ast`` module, so the checks give the same
answer on every Python version and cost no network and no third-party package.
"""

import ast
import os
import re
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Iterator, List, Tuple

ROOT = Path(__file__).resolve().parents[1]

# Code of this project (the vendored TeamTalk SDK wrapper in TeamTalkPy/ is not ours).
SOURCE_DIRS = ("bot", "tools")
SOURCE_FILES = ("TTMediaBot.py", "downloader.py")

# Modules removed from the standard library by Python 3.13 (PEP 594) or earlier.
REMOVED_MODULES = {
    "imp", "distutils", "asyncore", "asynchat", "smtpd", "cgi", "cgitb", "telnetlib",
    "pipes", "crypt", "nntplib", "imghdr", "sndhdr", "audioop", "aifc", "sunau",
    "chunk", "uu", "xdrlib", "mailcap", "msilib", "ossaudiodev", "spwd", "nis",
    "lib2to3", "pkg_resources", "sre_compile", "sre_constants", "sre_parse",
}

# Attributes of the standard library that are deprecated or already removed.
REMOVED_ATTRIBUTES = {
    "load_module": "use importlib.util.spec_from_file_location + exec_module (bot.utils.load_python_module)",
    "find_module": "use find_spec",
    "utcnow": "use datetime.now(timezone.utc)",
    "utcfromtimestamp": "use datetime.fromtimestamp(ts, timezone.utc)",
    "getdefaultlocale": "use locale.getlocale() or an explicit encoding",
    "wrap_socket": "use ssl.SSLContext.wrap_socket",
    "SetPointerType": "removed from ctypes in Python 3.15",
    "glob0": "removed from glob in Python 3.15",
    "glob1": "removed from glob in Python 3.15",
    "java_ver": "removed from platform in Python 3.15",
    "getargspec": "use inspect.signature",
    "co_lnotab": "use co_lines()",
    "no_type_check_decorator": "removed from typing in Python 3.15",
}


def source_files() -> Iterator[Path]:
    for name in SOURCE_DIRS:
        for path in sorted((ROOT / name).rglob("*.py")):
            if "__pycache__" not in path.parts:
                yield path
    for name in SOURCE_FILES:
        path = ROOT / name
        if path.is_file():
            yield path


def parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def where(path: Path, node: ast.AST) -> str:
    return "{}:{}".format(path.relative_to(ROOT).as_posix(), getattr(node, "lineno", "?"))


class SourceCompatibilityTests(unittest.TestCase):
    def test_every_file_is_valid_for_python_3_10(self):
        # feature_version makes the parser refuse newer syntax (for example the
        # "lazy import" statement of Python 3.15, which older versions cannot read).
        for path in source_files():
            with self.subTest(file=where(path, ast.Pass())):
                ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 10))

    def test_libraries_that_most_bots_never_use_are_loaded_lazily(self):
        # pyshorteners belongs to a feature that is off by default; bs4 is only needed when a
        # web page has to be read. On Python 3.15 they are loaded at first use.
        expected = {
            "bot/modules/shortener.py": "pyshorteners",
            "bot/modules/stream_resolvers.py": "bs4",
        }
        for name, library in expected.items():
            with self.subTest(file=name):
                tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
                declared = []
                for node in tree.body:
                    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__lazy_modules__" for t in node.targets):
                        declared = [c.value for c in node.value.elts if isinstance(c, ast.Constant)]
                self.assertIn(library, declared)

    def test_the_lazy_keyword_is_not_used(self):
        # Only __lazy_modules__ is allowed: it is a plain list on older versions.
        pattern = re.compile(r"^\s*lazy\s+(import|from)\b", re.MULTILINE)
        for path in source_files():
            with self.subTest(file=path.relative_to(ROOT).as_posix()):
                self.assertIsNone(pattern.search(path.read_text(encoding="utf-8")))

    def test_no_module_removed_from_the_standard_library_is_imported(self):
        problems: List[str] = []
        for path in source_files():
            for node in ast.walk(parse(path)):
                names: List[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                for name in names:
                    if name.split(".")[0] in REMOVED_MODULES:
                        problems.append("{} imports {}".format(where(path, node), name))
        self.assertEqual(problems, [])

    def test_no_deprecated_or_removed_standard_library_call(self):
        problems: List[str] = []
        for path in source_files():
            for node in ast.walk(parse(path)):
                if isinstance(node, ast.Attribute) and node.attr in REMOVED_ATTRIBUTES:
                    problems.append(
                        "{} uses .{}: {}".format(where(path, node), node.attr, REMOVED_ATTRIBUTES[node.attr])
                    )
        self.assertEqual(problems, [])

    def test_text_files_always_name_their_encoding(self):
        # Python 3.15 reads text as UTF-8 by default and older versions on Windows
        # use the code page. An explicit encoding gives the same result everywhere.
        problems: List[str] = []
        for path in source_files():
            for node in ast.walk(parse(path)):
                if not isinstance(node, ast.Call):
                    continue
                keywords = {k.arg for k in node.keywords}
                if None in keywords:  # **options: cannot be judged
                    continue
                func = node.func
                if isinstance(func, ast.Name) and func.id == "open":
                    mode = ""
                    if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                        mode = str(node.args[1].value)
                    elif "mode" in keywords:
                        value = next(k.value for k in node.keywords if k.arg == "mode")
                        mode = str(value.value) if isinstance(value, ast.Constant) else "b"
                    if "b" not in mode and "encoding" not in keywords:
                        problems.append("{} open() without encoding".format(where(path, node)))
                elif isinstance(func, ast.Attribute) and func.attr in ("read_text", "write_text"):
                    if "encoding" not in keywords:
                        problems.append("{} {}() without encoding".format(where(path, node), func.attr))
        self.assertEqual(problems, [])

    def test_subprocess_text_mode_names_its_encoding(self):
        problems: List[str] = []
        for path in source_files():
            for node in ast.walk(parse(path)):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                    continue
                if not (isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess"):
                    continue
                keywords = {k.arg: k.value for k in node.keywords}
                text_mode = any(
                    isinstance(keywords.get(name), ast.Constant) and keywords[name].value is True
                    for name in ("text", "universal_newlines")
                )
                if text_mode and "encoding" not in keywords:
                    problems.append("{} subprocess text mode without encoding".format(where(path, node)))
        self.assertEqual(problems, [])


class EventHandlerLoaderTests(unittest.TestCase):
    def test_the_event_thread_uses_the_replacement_for_load_module(self):
        source = (ROOT / "bot" / "TeamTalk" / "thread.py").read_text(encoding="utf-8")
        self.assertIn("utils.load_python_module(", source)
        self.assertNotIn("SourceFileLoader", source)
        self.assertNotIn("load_module(", source)


class LazyModulesTests(unittest.TestCase):
    """__lazy_modules__ (PEP 810) must be defined before the imports it makes lazy."""

    def test_declarations_are_well_formed_and_come_first(self):
        declared = 0
        for path in source_files():
            tree = parse(path)
            for index, node in enumerate(tree.body):
                is_declaration = (
                    isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "__lazy_modules__" for t in node.targets)
                )
                if not is_declaration:
                    continue
                declared += 1
                label = where(path, node)
                self.assertIsInstance(node.value, (ast.List, ast.Tuple), label)
                names = []
                for element in node.value.elts:
                    self.assertIsInstance(element, ast.Constant, label)
                    self.assertIsInstance(element.value, str, label)
                    names.append(element.value)
                for name in names:
                    imports = [
                        (i, later) for i, later in enumerate(tree.body)
                        if (isinstance(later, ast.Import) and any(a.name == name for a in later.names))
                        or (isinstance(later, ast.ImportFrom) and later.module == name and later.level == 0)
                    ]
                    self.assertTrue(imports, "{}: {} is not imported at module level".format(label, name))
                    for position, later in imports:
                        self.assertGreater(
                            position, index,
                            "{}: {} is imported before __lazy_modules__ is defined".format(label, name),
                        )
        self.assertGreater(declared, 0, "no module declares __lazy_modules__ any more")


class LoadPythonModuleTests(unittest.TestCase):
    def setUp(self):
        from bot import utils

        self.utils = utils
        self.cwd = os.getcwd()
        self.root = tempfile.mkdtemp()
        os.chdir(self.root)
        self.loaded: List[str] = []

    def tearDown(self):
        os.chdir(self.cwd)
        for name in self.loaded:
            sys.modules.pop(name, None)
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, name: str, text: str) -> None:
        with open(os.path.join(self.root, name), "w", encoding="utf-8") as f:
            f.write(text)

    def test_a_file_with_a_relative_path_is_loaded(self):
        self.write("handlers_a.py", "TITLE = 'Lagu: Bersenja Gurau \u2014 caf\u00e9 \u97f3\u697d'\n\ndef on_ready():\n    return 7\n")
        self.loaded.append("handlers_a")
        module = self.utils.load_python_module("handlers_a", "handlers_a.py")
        self.assertEqual(module.on_ready(), 7)
        self.assertEqual(module.TITLE, "Lagu: Bersenja Gurau \u2014 caf\u00e9 \u97f3\u697d")
        self.assertIs(sys.modules["handlers_a"], module)
        self.assertEqual(module.__name__, "handlers_a")

    def test_a_package_directory_is_loaded_with_its_submodules(self):
        os.mkdir(os.path.join(self.root, "handlers_pkg"))
        self.write("handlers_pkg/__init__.py", "from . import extra\nVALUE = extra.NUMBER + 1\n")
        self.write("handlers_pkg/extra.py", "NUMBER = 41\n")
        self.loaded += ["handlers_pkg", "handlers_pkg.extra"]
        module = self.utils.load_python_module("handlers_pkg", "handlers_pkg/__init__.py")
        self.assertEqual(module.VALUE, 42)
        self.assertEqual(list(module.__path__), ["handlers_pkg"])

    def test_a_file_that_fails_is_not_left_in_sys_modules(self):
        self.write("handlers_bad.py", "raise RuntimeError('boom')\n")
        with self.assertRaises(RuntimeError):
            self.utils.load_python_module("handlers_bad", "handlers_bad.py")
        self.assertNotIn("handlers_bad", sys.modules)

    def test_a_missing_file_is_an_error_the_caller_can_catch(self):
        with self.assertRaises(Exception):
            self.utils.load_python_module("handlers_none", "handlers_none.py")
        self.assertNotIn("handlers_none", sys.modules)

    def test_loading_twice_gives_the_current_content(self):
        # The two texts have different lengths: Python decides whether a cached .pyc is
        # still valid from the modification time (one second apart at best) and the size.
        self.write("handlers_c.py", "VALUE = 1\n")
        self.loaded.append("handlers_c")
        self.assertEqual(self.utils.load_python_module("handlers_c", "handlers_c.py").VALUE, 1)
        self.write("handlers_c.py", "VALUE = 200\n")
        self.assertEqual(self.utils.load_python_module("handlers_c", "handlers_c.py").VALUE, 200)


class ConfigDumpTests(unittest.TestCase):
    def test_pydantic_2_name_is_preferred_and_pydantic_1_still_works(self):
        from bot.config import dump_model

        class Two:
            def model_dump(self):
                return {"from": "model_dump"}

            def dict(self):  # pydantic 2 keeps it, deprecated
                raise AssertionError("dict() must not be used when model_dump() exists")

        class One:
            def dict(self):
                return {"from": "dict"}

        self.assertEqual(dump_model(Two()), {"from": "model_dump"})
        self.assertEqual(dump_model(One()), {"from": "dict"})

    def test_the_real_configuration_dumps_every_section(self):
        from bot.config import dump_model
        from bot.config.models import ConfigModel

        data = dump_model(ConfigModel())
        for section in ("general", "player", "teamtalk", "services", "logger", "ai"):
            self.assertIn(section, data)


class PythonVersionGuardTests(unittest.TestCase):
    def guard(self) -> ast.If:
        tree = parse(ROOT / "TTMediaBot.py")
        first_import_of_bot = next(
            i for i, node in enumerate(tree.body)
            if isinstance(node, ast.ImportFrom) and node.module == "bot"
        )
        guards = [
            (i, node) for i, node in enumerate(tree.body)
            if isinstance(node, ast.If) and "version_info" in ast.dump(node.test)
        ]
        self.assertTrue(guards, "TTMediaBot.py has no Python version guard")
        self.assertLess(guards[0][0], first_import_of_bot, "the guard must run before the bot is imported")
        return guards[0][1]

    def run_guard(self, version: Tuple[int, ...]) -> str:
        fake_sys = types.SimpleNamespace(version_info=version + ("final", 0))

        def fake_exit(message=None):
            raise SystemExit(message)

        fake_sys.exit = fake_exit
        module = ast.Module(body=[self.guard()], type_ignores=[])
        ast.fix_missing_locations(module)
        try:
            exec(compile(module, "TTMediaBot.py", "exec"), {"sys": fake_sys})
        except SystemExit as stop:
            return str(stop.code)
        return ""

    def test_python_3_9_gets_a_clear_message(self):
        message = self.run_guard((3, 9, 18))
        self.assertIn("3.10", message)
        self.assertIn("3.15", message)
        self.assertIn("3.9.18", message)

    def test_supported_versions_pass(self):
        for version in ((3, 10, 0), (3, 12, 3), (3, 14, 1), (3, 15, 0)):
            with self.subTest(version=version):
                self.assertEqual(self.run_guard(version), "")


class WindowsScriptTests(unittest.TestCase):
    """install_windows.bat and TTMediaBot.bat cannot run here; their text is checked."""

    def setUp(self):
        self.raw = (ROOT / "install_windows.bat").read_bytes()
        self.text = self.raw.decode("utf-8").replace("\r\n", "\n")
        self.lines = self.text.split("\n")

    def test_batch_files_do_not_mix_line_endings(self):
        # A batch file with bare LF line endings can break "goto" and "call" labels, so
        # on Windows every line must end in CRLF. Git stores the files with LF and
        # Windows checks them out with CRLF; on another system a pure-LF copy is
        # accepted here, a mixture of both never is.
        for name in ("install_windows.bat", "TTMediaBot.bat"):
            raw = (ROOT / name).read_bytes()
            lines = raw.count(b"\n")
            bare_lf = lines - raw.count(b"\r\n")
            with self.subTest(file=name):
                self.assertIn(bare_lf, (0, lines), "CRLF and bare LF are mixed")
                if os.name == "nt":
                    self.assertEqual(bare_lf, 0, "bare LF found")

    def test_every_goto_and_call_has_its_label(self):
        labels = re.findall(r"^:([A-Za-z0-9_]+)\s*$", self.text, flags=re.MULTILINE)
        self.assertEqual(len(labels), len(set(labels)), "a label is defined twice")
        targets = set(re.findall(r"\bgoto\s+:?([A-Za-z0-9_]+)", self.text, flags=re.IGNORECASE))
        targets |= set(re.findall(r"\bcall\s+:([A-Za-z0-9_]+)", self.text, flags=re.IGNORECASE))
        targets.discard("eof")
        self.assertEqual(sorted(t for t in targets if t not in labels), [])

    def test_python_one_liners_have_no_batch_escapes(self):
        # Inside double quotes a caret is not an escape: Python would receive it.
        for line in self.lines:
            if re.search(r'\s-c\s+"', line):
                self.assertNotIn("^", line, line)

    def test_comments_have_no_redirection_characters(self):
        for line in self.lines:
            if re.match(r"\s*rem\b", line, flags=re.IGNORECASE):
                self.assertIsNone(re.search(r"[<>&|^]", line), line)

    def test_python_3_15_is_installed_with_the_official_commands(self):
        # the line that runs (not only the one that is printed) carries the official id
        self.assertRegex(
            self.text,
            r"(?m)^winget install 9NQ7512CXL7T --accept-package-agreements( --accept-source-agreements)?$",
        )
        self.assertRegex(self.text, r'(?m)^"%PYM%" install -y 3\.15$')
        self.assertRegex(self.text, r'(?m)^"%PYM%" install --configure -y$')
        self.assertIn("py -V:3.15", self.text)
        # Older Pythons keep working: 3.10 or newer, 64-bit.
        self.assertIn("(3, 10)", self.text)
        self.assertIn("2**32", self.text)

    def test_step_4_is_a_question_and_a_no_skips_steps_4_and_5(self):
        start = self.text.index("[4/6]")
        question = self.text.index("set /p", start)
        self.assertLess(start, question)
        self.assertIn(':pot_declined', self.text)
        declined = self.text[self.text.index(":pot_declined\n"):]
        declined = declined[: declined.index(":pot_install\n")]
        self.assertIn("[5/6] Skipped", declined)
        self.assertIn("goto launch_done", declined)
        # the installation and the launch are not reached through the "no" branch
        self.assertNotIn("git clone", declined)
        self.assertNotIn("node build", declined)
        for answer in ("n", "no"):
            self.assertRegex(self.text, r'if /i "%ANSWER%"=="{}" goto pot_declined'.format(answer))
        for answer in ("y", "yes"):
            self.assertRegex(self.text, r'if /i "%ANSWER%"=="{}" goto pot_install'.format(answer))
        # unattended runs
        self.assertIn('"--no-pot" set "POT_CHOICE=N"', self.text)
        self.assertIn('"--pot" set "POT_CHOICE=Y"', self.text)

    def test_an_answer_is_asked_again_when_it_is_not_yes_or_no(self):
        block = self.text[self.text.index(":pot_ask\n"):]
        block = block[: block.index(":pot_declined\n")]
        self.assertIn("Please type Y or N", block)
        self.assertTrue(block.rstrip().endswith("goto pot_ask"))

    def test_the_provider_is_only_installed_after_a_yes(self):
        self.assertLess(self.text.index(":pot_install\n"), self.text.index("git clone"))
        self.assertLess(self.text.index(":pot_declined\n"), self.text.index(":pot_install\n"))

    def test_utf8_is_set_for_older_pythons(self):
        self.assertIn('if not defined PYTHONUTF8 set "PYTHONUTF8=1"', self.text)
        launcher = (ROOT / "TTMediaBot.bat").read_text(encoding="utf-8")
        self.assertIn('if not defined PYTHONUTF8 set "PYTHONUTF8=1"', launcher)


class VersionTests(unittest.TestCase):
    def test_the_changelog_describes_the_running_version(self):
        from bot import app_vars

        self.assertRegex(app_vars.app_version, r"^\d+\.\d+\.\d+$")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("Version {}".format(app_vars.app_version), changelog)


if __name__ == "__main__":
    unittest.main()
