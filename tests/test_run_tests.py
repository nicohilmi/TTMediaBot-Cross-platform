"""tools/run_tests.py, run_tests.bat and the line endings that make them work on Windows."""
import contextlib
import io
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from tools import run_tests as rt

ROOT = Path(__file__).resolve().parents[1]
SKIPPED_DIRECTORIES = {".git", "venv", "node_modules", "__pycache__"}


def repository_files(pattern):
    return [
        path
        for path in sorted(ROOT.rglob(pattern))
        if not SKIPPED_DIRECTORIES.intersection(path.relative_to(ROOT).parts)
    ]


class MissingPackagesTests(TestCase):
    def test_everything_installed_gives_an_empty_list(self):
        self.assertEqual(rt.missing_packages(lambda name: object()), [])

    def test_a_missing_package_is_named_with_its_pip_name(self):
        found = rt.missing_packages(lambda name: None if name == "bs4" else object())
        self.assertEqual(found, [("bs4", "beautifulsoup4")])

    def test_a_missing_parent_package_counts_as_missing(self):
        def find_spec(name):
            if name == "google.genai":
                raise ModuleNotFoundError("No module named 'google'")
            return object()

        self.assertEqual(rt.missing_packages(find_spec), [("google.genai", "google-genai")])

    def test_the_list_matches_requirements_txt(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
        for _module, package in rt.REQUIRED_PACKAGES:
            self.assertIn(package.split("[")[0].lower(), requirements, package)


class SkipReportTests(TestCase):
    def test_every_reason_is_listed_with_its_count(self):
        lines = rt.describe_skips(Counter({"bash is required": 4, "no curl": 1}))
        self.assertEqual(lines, ["    4 x bash is required", "    1 x no curl"])


class NodeTestsTests(TestCase):
    def fake_run(self, returncode, stdout):
        seen = {}

        def run(command, **kwargs):
            seen["command"], seen["kwargs"] = command, kwargs
            return SimpleNamespace(returncode=returncode, stdout=stdout)

        run.seen = seen
        return run

    def test_without_node_the_tests_are_skipped_not_failed(self):
        passed, reason = rt.run_node_tests(run=self.fake_run(0, ""), which=lambda name: None)
        self.assertIsNone(passed)
        self.assertIn("Node.js was not found", reason)

    def test_a_passing_run_is_summarised(self):
        run = self.fake_run(0, "ok 1 - a\n# tests 9\n# suites 0\n# pass 9\n# fail 0\n")
        passed, summary = rt.run_node_tests(run=run, which=lambda name: "node")
        self.assertTrue(passed)
        self.assertEqual(summary, "9 tests, 0 failed")
        self.assertEqual(run.seen["command"], ["node", "--test"])
        self.assertEqual(Path(run.seen["kwargs"]["cwd"]), ROOT / "youtube_bridge")

    def test_the_summary_of_the_spec_reporter_is_read_too(self):
        # Newer Node versions print "ℹ tests 9" instead of "# tests 9"; the summary used to show "?".
        run = self.fake_run(0, "✔ a (1ms)\nℹ tests 9\nℹ suites 0\nℹ pass 9\nℹ fail 0\nℹ cancelled 0\n")
        passed, summary = rt.run_node_tests(run=run, which=lambda name: "node")
        self.assertTrue(passed)
        self.assertEqual(summary, "9 tests, 0 failed")

    def test_a_failing_run_fails(self):
        run = self.fake_run(1, "not ok 3 - b\n# tests 9\n# pass 8\n# fail 1\n")
        shown = io.StringIO()
        with contextlib.redirect_stdout(shown):
            passed, summary = rt.run_node_tests(run=run, which=lambda name: "node")
        self.assertIn("not ok 3 - b", shown.getvalue(), "the details of a failure must be shown")
        self.assertFalse(passed)
        self.assertEqual(summary, "9 tests, 1 failed")

    def test_node_that_cannot_start_fails(self):
        def run(command, **kwargs):
            raise OSError("not executable")

        passed, summary = rt.run_node_tests(run=run, which=lambda name: "node")
        self.assertFalse(passed)
        self.assertIn("not executable", summary)


class RunnerSmokeTests(TestCase):
    """The real script in a real process, on a handful of fast tests."""

    def run_script(self, *arguments):
        env = dict(os.environ, PYTHONUTF8="1")
        return subprocess.run(
            [sys.executable, str(ROOT / "tools" / "run_tests.py"), *arguments],
            cwd=str(ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )

    def test_a_filtered_run_passes_and_says_so(self):
        result = self.run_script("--no-node", "-k", "test_split_message")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("ALL TESTS PASSED", result.stdout)

    def test_a_pattern_that_matches_nothing_is_a_failure(self):
        result = self.run_script("--no-node", "-k", "no_test_has_this_name_xyz")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("TESTS FAILED", result.stdout)
        self.assertIn("no test was found", result.stdout)


class WindowsLauncherTests(TestCase):
    def setUp(self):
        self.text = (ROOT / "run_tests.bat").read_text(encoding="utf-8")

    def test_it_runs_the_runner_with_the_virtual_environment_python(self):
        self.assertIn(r"venv\Scripts\python.exe", self.text)
        self.assertIn(r"tools\run_tests.py %*", self.text)

    def test_it_runs_from_its_own_folder_with_utf8_and_returns_the_result(self):
        self.assertIn('cd /d "%~dp0"', self.text)
        self.assertIn('set "PYTHONUTF8=1"', self.text)
        self.assertIn("exit /b %RESULT%", self.text)


class LineEndingTests(TestCase):
    """cmd.exe needs CRLF in .bat files and bash needs LF in .sh files, on every clone."""

    def test_batch_files_have_crlf_line_endings(self):
        for path in repository_files("*.bat"):
            data = path.read_bytes()
            with self.subTest(file=path.name):
                self.assertEqual(data.count(b"\n"), data.count(b"\r\n"), f"{path.name} has bare LF lines")

    def test_shell_scripts_have_lf_line_endings(self):
        for path in repository_files("*.sh"):
            with self.subTest(file=path.name):
                self.assertNotIn(
                    b"\r\n", path.read_bytes(),
                    f"{path.name} has CRLF: run  git add --renormalize .  (see .gitattributes)",
                )

    def test_gitattributes_keeps_them_that_way(self):
        rules = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("*.bat text eol=crlf", rules)
        self.assertIn("*.sh text eol=lf", rules)


class DeploymentTestsOnWindowsTests(TestCase):
    """The bash-script tests are for Linux; on Windows they are skipped, never failed."""

    def test_bash_is_not_used_on_windows_even_when_a_bash_exists(self):
        from tests.deployment import bash_sandbox

        with patch.object(bash_sandbox.shutil, "which", return_value="C:/Windows/System32/bash.exe"):
            with patch.object(bash_sandbox.os, "name", "nt"):
                self.assertIsNone(bash_sandbox.find_bash())
            if os.name != "nt":
                self.assertEqual(bash_sandbox.find_bash(), "C:/Windows/System32/bash.exe")

    def test_the_skip_reason_says_where_to_run_them(self):
        from tests.deployment import bash_sandbox

        self.assertIn("Linux", bash_sandbox.SKIP_REASON)
        self.assertIn("WSL", bash_sandbox.SKIP_REASON)
