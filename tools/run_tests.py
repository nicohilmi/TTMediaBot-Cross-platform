#!/usr/bin/env python3
"""Run every test of the project. Run this before every git commit.

    run_tests.bat                       (Windows; uses venv\\Scripts\\python.exe)
    python tools/run_tests.py           (any system)
    python tools/run_tests.py -v        (one line per test)
    python tools/run_tests.py -k fade   (only the tests whose name contains "fade")
    python tools/run_tests.py -f        (stop at the first failure)

What it runs:

* every test in ``tests/`` (``unittest``), including the ones in ``tests/deployment``;
* the Node tests of the YouTube bridge (``node --test`` in ``youtube_bridge/``), when
  Node.js is installed.

No test needs the internet, a TeamTalk server or the native TeamTalk library: the tests
import the bot with a stand-in for ``TeamTalk5.dll`` (see ``tests/__init__.py``; set
``TTBOT_TEST_REAL_SDK=1`` to load the real one). Tests that cannot run on this computer
(for example the bash scripts of the Linux deployment on Windows) are listed as skipped
with their reason, so nothing is skipped silently.

The exit code is 0 only when everything passed.
"""
from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
import time
import unittest
from collections import Counter
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent

# (module to import, what to pip install when it is missing)
REQUIRED_PACKAGES = (
    ("pydantic", "pydantic"),
    ("portalocker", "portalocker"),
    ("requests", "requests"),
    ("numpy", "numpy"),
    ("bs4", "beautifulsoup4"),
    ("httpx", "httpx[http2]"),
    ("google.genai", "google-genai"),
    ("pyshorteners", "pyshorteners"),
    ("babel", "babel"),
)


def missing_packages(
    find_spec: Callable[[str], object] = importlib.util.find_spec,
) -> List[Tuple[str, str]]:
    """The (module, pip name) pairs that cannot be imported with this Python."""
    missing = []
    for module, package in REQUIRED_PACKAGES:
        try:
            found = find_spec(module)
        except (ImportError, ValueError):
            found = None
        if found is None:
            missing.append((module, package))
    return missing


class _Result(unittest.TextTestResult):
    """A text result that also remembers why tests were skipped."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.skip_reasons: Counter = Counter()

    def addSkip(self, test, reason) -> None:  # noqa: N802 - the name unittest uses
        self.skip_reasons[reason] += 1
        super().addSkip(test, reason)


def describe_skips(reasons: Counter) -> List[str]:
    return [f"    {count} x {reason}" for reason, count in sorted(reasons.items())]


def run_python_tests(verbosity: int, failfast: bool, pattern: Optional[str]) -> Tuple[bool, str]:
    """Run tests/ in this process. Returns (passed, one-line summary)."""
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    if pattern:
        suite = _filter(suite, pattern.lower())
    runner = unittest.TextTestRunner(
        verbosity=verbosity, failfast=failfast, resultclass=_Result, buffer=False
    )
    result = runner.run(suite)
    problems = len(result.failures) + len(result.errors)
    summary = f"{result.testsRun} tests, {problems} failed, {len(result.skipped)} skipped"
    if result.skip_reasons:
        print("\n  Skipped on this computer:")
        print("\n".join(describe_skips(result.skip_reasons)))
    passed = result.wasSuccessful() and result.testsRun > 0
    if result.testsRun == 0:
        summary += " (no test was found: check the pattern)"
    return passed, summary


def _filter(suite: unittest.TestSuite, text: str) -> unittest.TestSuite:
    kept = unittest.TestSuite()
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            inner = _filter(item, text)
            if inner.countTestCases():
                kept.addTest(inner)
        elif text in item.id().lower():
            kept.addTest(item)
    return kept


def run_node_tests(
    run: Callable[..., "subprocess.CompletedProcess[str]"] = subprocess.run,
    which: Callable[[str], Optional[str]] = shutil.which,
) -> Tuple[Optional[bool], str]:
    """The Node tests of the YouTube bridge. (None, reason) when Node.js is not installed."""
    node = which("node")
    if not node:
        return None, "Node.js was not found; the YouTube bridge tests were not run"
    try:
        result = run(
            [node, "--test"],
            cwd=str(ROOT / "youtube_bridge"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, f"node could not run the tests: {error}"
    # Node prints "# tests 5" (TAP) or "ℹ tests 5" (the spec reporter of newer Node versions).
    counts = {}
    for line in (result.stdout or "").splitlines():
        parts = line.strip().lstrip("#ℹ").split()
        if len(parts) == 2 and parts[0] in ("tests", "pass", "fail") and parts[1].isdigit():
            counts[parts[0]] = parts[1]
    summary = "{} tests, {} failed".format(counts.get("tests", "?"), counts.get("fail", "?"))
    if result.returncode != 0:
        print(result.stdout)
    return result.returncode == 0, summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run every test of TTMediaBot.")
    parser.add_argument("-v", "--verbose", action="store_true", help="one line per test")
    parser.add_argument("-f", "--failfast", action="store_true", help="stop at the first failure")
    parser.add_argument("-k", dest="pattern", help="only tests whose name contains this text")
    parser.add_argument("--no-node", action="store_true", help="do not run the YouTube bridge (Node.js) tests")
    args = parser.parse_args(argv)

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    print(f"Python {sys.version.split()[0]} ({sys.executable})")
    missing = missing_packages()
    if missing:
        print("\nThese Python packages are missing, so the tests cannot run:")
        for module, package in missing:
            print(f"    {module}   (pip install {package})")
        print("\nInstall everything the bot needs with:")
        print(f'    "{sys.executable}" -m pip install -r requirements.txt')
        print("(install_windows.bat does this too.) Then run the tests again.")
        return 2

    started = time.time()
    print("\n== Python tests (tests/) ==")
    print("(WARNING / ERROR lines printed below are log messages of tests that exercise failure")
    print(" paths on purpose; only the result at the end counts.)")
    python_ok, python_summary = run_python_tests(2 if args.verbose else 1, args.failfast, args.pattern)

    node_ok: Optional[bool] = None
    node_summary = "not run (--no-node)"
    if not args.no_node and not args.pattern:
        print("\n== YouTube bridge tests (Node.js) ==")
        node_ok, node_summary = run_node_tests()

    print("\n" + "=" * 62)
    print(f"  Python tests : {'PASSED' if python_ok else 'FAILED'}  ({python_summary})")
    if node_ok is None:
        print(f"  Node tests   : skipped  ({node_summary})")
    else:
        print(f"  Node tests   : {'PASSED' if node_ok else 'FAILED'}  ({node_summary})")
    print(f"  Time         : {time.time() - started:.1f} s")
    ok = python_ok and node_ok is not False
    print("  RESULT       : " + ("ALL TESTS PASSED - it is safe to commit." if ok else "TESTS FAILED - do not commit yet."))
    print("=" * 62)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
