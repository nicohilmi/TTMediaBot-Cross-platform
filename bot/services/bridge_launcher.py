"""Start the YouTube.js bridge (``youtube_bridge/server.mjs``) when it is not
already running.

In the Docker deployment the bridge is a shared container and nothing here
runs: its health endpoint already answers. When the bot runs directly on
Windows or Linux, the bot starts the bridge itself with Node.js, as a child
process that is stopped again when the bot exits.

Set ``YOUTUBE_BRIDGE_AUTOSTART=0`` to disable this and manage the bridge
yourself.
"""

from __future__ import annotations

import atexit
import logging
import os
import shutil
import subprocess
import threading
from typing import Optional
from urllib.parse import urlparse

import requests

from bot import app_vars
from bot.ffmpeg_locator import hidden_process_kwargs

BRIDGE_DIR = os.path.join(app_vars.directory, "youtube_bridge")
SERVER_FILE = os.path.join(BRIDGE_DIR, "server.mjs")
LOCAL_INSTANCE = "local"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}

_lock = threading.Lock()
_process: Optional[subprocess.Popen] = None
_log_file = None


def is_standalone() -> bool:
    """True when the bot is not part of the Docker multi-bot deployment."""
    return not os.getenv("TTBOT_INSTANCE")


def instance_name() -> str:
    return os.getenv("TTBOT_INSTANCE") or LOCAL_INSTANCE


def local_bots_root() -> str:
    return os.getenv("TTMEDIABOT_BOTS_ROOT") or os.path.join(
        app_vars.directory, "data", "bots"
    )


def is_healthy(base_url: str) -> bool:
    try:
        return requests.get(f"{base_url}/health", timeout=(1, 2)).ok
    except requests.RequestException:
        return False


def sync_cookie_file(cookie_file: str) -> None:
    """The bridge reads cookies from ``<bots root>/<instance>/cookies.txt``.
    In standalone mode copy the cookie file named in config.json there."""
    if not is_standalone() or not cookie_file or not os.path.isfile(cookie_file):
        return
    target_dir = os.path.join(local_bots_root(), instance_name())
    target = os.path.join(target_dir, "cookies.txt")
    try:
        os.makedirs(target_dir, exist_ok=True)
        if (
            not os.path.isfile(target)
            or os.path.getmtime(target) < os.path.getmtime(cookie_file)
            or os.path.getsize(target) != os.path.getsize(cookie_file)
        ):
            shutil.copyfile(cookie_file, target)
            logging.info(f"[YouTubeBridge] Cookie file copied to {target}")
    except OSError as error:
        logging.warning(f"[YouTubeBridge] Could not copy the cookie file: {error}")


def ensure_running(base_url: str, cookie_file: str = "") -> bool:
    """Make sure a bridge answers on ``base_url``. Returns True when it is
    (or is being) started; False when it cannot be started here."""
    global _process, _log_file
    sync_cookie_file(cookie_file)
    if os.getenv("YOUTUBE_BRIDGE_AUTOSTART", "1").lower() in ("0", "false", "no", "off"):
        return False
    with _lock:
        if _process is not None and _process.poll() is None:
            return True
        if is_healthy(base_url):
            return True
        parsed = urlparse(base_url)
        if (parsed.hostname or "") not in LOCAL_HOSTS:
            logging.warning(
                f"[YouTubeBridge] {base_url} is not reachable and is not a local address, "
                "so it will not be started automatically."
            )
            return False
        if not os.path.isfile(SERVER_FILE):
            logging.error(f"[YouTubeBridge] {SERVER_FILE} is missing.")
            return False
        node = shutil.which("node")
        if not node:
            logging.error(
                "[YouTubeBridge] Node.js was not found. Install Node.js (LTS) so that "
                "'node' works in a terminal; YouTube playback needs it."
            )
            return False
        if not os.path.isdir(os.path.join(BRIDGE_DIR, "node_modules", "youtubei.js")):
            logging.error(
                "[YouTubeBridge] Dependencies are not installed. Run 'npm install "
                "--omit=dev' inside the youtube_bridge folder (Git must be installed)."
            )
            return False

        env = os.environ.copy()
        env["YOUTUBE_BRIDGE_HOST"] = parsed.hostname or "127.0.0.1"
        env["YOUTUBE_BRIDGE_PORT"] = str(parsed.port or 4417)
        env.setdefault("TTMEDIABOT_BOTS_ROOT", local_bots_root())
        os.makedirs(local_bots_root(), exist_ok=True)
        log_path = os.path.join(app_vars.directory, "youtube_bridge.log")
        try:
            _log_file = open(log_path, "ab")
            _process = subprocess.Popen(
                [node, SERVER_FILE],
                cwd=BRIDGE_DIR,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=_log_file,
                stderr=subprocess.STDOUT,
                **hidden_process_kwargs(),
            )
        except OSError as error:
            logging.error(f"[YouTubeBridge] Could not start Node.js: {error}")
            return False
        atexit.register(stop)
        logging.info(
            f"[YouTubeBridge] Started the YouTube.js bridge (pid {_process.pid}), "
            f"log: {log_path}"
        )
        return True


def stop() -> None:
    """Stop the bridge if this bot started it."""
    global _process, _log_file
    with _lock:
        process, _process = _process, None
        log_file, _log_file = _log_file, None
    if process is not None and process.poll() is None:
        try:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        except OSError:
            pass
    if log_file is not None:
        try:
            log_file.close()
        except OSError:
            pass
