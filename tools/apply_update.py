"""Finishes an update while the bot starts, before the bot itself is loaded.

An operating system installs the parts of an update that cannot be replaced while
they are in use during the restart. This does the same for the Python packages:
when the ``install`` command finds that an update changed requirements.txt, it
leaves a note (bot/update_state.py) and restarts the bot. TTMediaBot.py runs ``run_pending()`` first
thing, in a fresh process that has loaded none of the packages yet, so pip can
replace them (on Windows a loaded package cannot be replaced).

The outcome is written to ``data/requirements_result.json``; the bot reads it
once it is online and tells the channel. A failure never stops the bot from
starting, and the step is never repeated by itself.
"""

import json
import os
import subprocess
import sys
import time
from typing import Any, Callable, Dict, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The same names are used by bot/update_state.py (a test keeps them equal).
PENDING_NAME = "requirements_pending"
RESULT_NAME = "requirements_result.json"
PIP_TIMEOUT_SECONDS = 900
# Time given to the previous process to end, so no file is still in use.
SETTLE_SECONDS = 3
MAX_ERROR_LENGTH = 220


def data_dir(root: str = ROOT) -> str:
    return os.path.join(root, "data")


def _short_error(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    text = " ".join(lines[-3:])
    if len(text) > MAX_ERROR_LENGTH:
        text = text[: MAX_ERROR_LENGTH - 3].rstrip() + "..."
    return text


def _install(root: str, runner: Callable[..., Any]) -> Dict[str, Any]:
    requirements = os.path.join(root, "requirements.txt")
    if not os.path.isfile(requirements):
        return {"ok": False, "error": "requirements.txt was not found"}
    command = [
        sys.executable, "-m", "pip", "install", "-r", requirements,
        "--disable-pip-version-check",
    ]
    try:
        done = runner(
            command,
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=PIP_TIMEOUT_SECONDS,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "pip did not finish within {} minutes".format(
            PIP_TIMEOUT_SECONDS // 60
        )}
    except OSError as error:
        return {"ok": False, "error": "pip could not be started: {}".format(error)}
    if done.returncode != 0:
        return {"ok": False, "error": _short_error(done.stdout or "") or
                "pip failed (exit code {})".format(done.returncode)}
    return {"ok": True, "error": ""}


def run_pending(
    root: str = ROOT,
    runner: Callable[..., Any] = subprocess.run,
    out: Callable[[str], None] = print,
    settle: float = SETTLE_SECONDS,
) -> Optional[Dict[str, Any]]:
    """Does what the last update asked for. Returns the outcome, or None when
    nothing was asked."""
    pending = os.path.join(data_dir(root), PENDING_NAME)
    if not os.path.exists(pending):
        return None
    try:
        # Removed first, so that whatever happens next the step is never repeated.
        os.remove(pending)
    except OSError:
        pass
    out("Finishing the update: installing the required Python packages...")
    if settle > 0:
        time.sleep(settle)
    result = _install(root, runner)
    try:
        os.makedirs(data_dir(root), exist_ok=True)
        with open(os.path.join(data_dir(root), RESULT_NAME), "w", encoding="utf-8") as f:
            json.dump(result, f)
    except OSError:
        pass
    if result["ok"]:
        out("The required Python packages are installed.")
    else:
        out("The Python packages could not be installed: {}".format(result["error"]))
    return result
