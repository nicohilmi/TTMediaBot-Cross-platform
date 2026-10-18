"""What an update leaves behind for the next start, and how the bot reports it.

Two small files carry information over a restart, as the "update installed"
screen of an operating system does:

* ``update_success`` (next to config.json): written by the ``install`` command
  with the version that was running. After the restart the bot says what changed.
* ``data/requirements_result.json``: written by tools/apply_update.py when the
  update had to install Python packages.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable, Dict, Optional

from bot import app_vars

SUCCESS_NAME = "update_success"
# The same names are used by tools/apply_update.py (a test keeps them equal).
REQUIREMENTS_PENDING_NAME = "requirements_pending"
REQUIREMENTS_RESULT_NAME = "requirements_result.json"


def success_path(config_dir: str) -> str:
    return os.path.join(config_dir, SUCCESS_NAME)


def write_success_marker(
    config_dir: str, from_commit: str = "", to_commit: str = ""
) -> None:
    data = {
        "from_version": app_vars.app_version,
        "from_commit": from_commit,
        "to_commit": to_commit,
    }
    with open(success_path(config_dir), "w", encoding="utf-8") as f:
        json.dump(data, f)


def read_success_marker(path: str) -> Dict[str, Any]:
    """The note left by ``install``. Older versions wrote the text "ok" only."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def request_requirements_install(root: Optional[str] = None) -> None:
    """Asks the next start to install requirements.txt (tools/apply_update.py)."""
    data_dir = os.path.join(root or app_vars.directory, "data")
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, REQUIREMENTS_PENDING_NAME), "w", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S"))


def completion_message(
    translate: Callable[[str], str], info: Dict[str, Any], migration: Any = None
) -> str:
    """The channel message sent when the bot is back online after an update."""
    lines = [translate("Update completed successfully! I am back online.")]
    old = str(info.get("from_version") or "")
    if old and old != app_vars.app_version:
        lines.append(
            translate("TTMediaBot was updated from version {old} to version {new}.").format(
                old=old, new=app_vars.app_version
            )
        )
    else:
        lines.append(
            translate("TTMediaBot is now version {version}.").format(
                version=app_vars.app_version
            )
        )
    count = int(getattr(migration, "added_count", 0) or 0)
    if count:
        lines.append(
            translate(
                "{count} new setting(s) were added to config.json. Your own settings were kept."
            ).format(count=count)
        )
    return "\n".join(lines)


def take_requirements_failure(root: str) -> Optional[str]:
    """Reads (and removes) the result of the package installation. Returns the
    error text when it failed, None when it succeeded or did not happen."""
    path = os.path.join(root, "data", REQUIREMENTS_RESULT_NAME)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            result = json.load(f)
    except (OSError, ValueError):
        result = {}
    try:
        os.remove(path)
    except OSError:
        pass
    if isinstance(result, dict) and result.get("ok") is False:
        return str(result.get("error") or "unknown error")
    return None
