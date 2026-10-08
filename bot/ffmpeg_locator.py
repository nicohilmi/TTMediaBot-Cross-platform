"""Locate the FFmpeg executable on Windows and Linux.

Search order:

1. ``player.ffmpeg_path`` from config.json (only when it is not empty),
2. the bot folder itself, next to ``TTMediaBot.py``
   (``ffmpeg.exe`` on Windows, ``ffmpeg`` on Linux/macOS),
3. whatever ``ffmpeg`` is installed system-wide and reachable through ``PATH``.

The result is cached, so the (cheap) probing happens once per process.
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
import subprocess
import sys
import threading
from typing import Any, Dict, List, Optional

from bot import app_vars

IS_WINDOWS = sys.platform == "win32"
EXECUTABLE_NAME = "ffmpeg.exe" if IS_WINDOWS else "ffmpeg"

_lock = threading.Lock()
_cached_path: Optional[str] = None
_cached_version: str = ""


class FFmpegNotFoundError(RuntimeError):
    pass


def hidden_process_kwargs() -> Dict[str, Any]:
    """Keyword arguments for subprocess so no console window pops up on Windows."""
    if IS_WINDOWS:
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


def local_ffmpeg_path() -> str:
    """Where a bundled ffmpeg is expected: in the top folder, beside TTMediaBot.py."""
    return os.path.join(app_vars.directory, EXECUTABLE_NAME)


def _make_executable(path: str) -> bool:
    if IS_WINDOWS or os.access(path, os.X_OK):
        return True
    try:
        mode = os.stat(path).st_mode
        os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError as error:
        logging.warning(
            f"[FFmpeg] '{path}' is not executable and chmod failed: {error}"
        )
        return False
    return os.access(path, os.X_OK)


def probe_version(path: str) -> Optional[str]:
    """Run ``ffmpeg -version`` and return its first line, or None when it fails."""
    try:
        result = subprocess.run(
            [path, "-hide_banner", "-version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
            **hidden_process_kwargs(),
        )
    except (OSError, subprocess.SubprocessError) as error:
        logging.debug(f"[FFmpeg] Probe of '{path}' failed: {error}")
        return None
    if result.returncode != 0:
        return None
    output = result.stdout.decode("utf-8", errors="replace").strip()
    return output.splitlines()[0] if output else None


def _candidates(configured: str) -> List[str]:
    candidates: List[str] = []
    configured = (configured or "").strip()
    if configured:
        expanded = os.path.expanduser(configured)
        if os.path.isdir(expanded):
            expanded = os.path.join(expanded, EXECUTABLE_NAME)
        elif not os.path.isabs(expanded) and os.path.dirname(expanded):
            expanded = os.path.join(app_vars.directory, expanded)
        candidates.append(expanded)
    candidates.append(local_ffmpeg_path())
    system_path = shutil.which("ffmpeg")
    if system_path:
        candidates.append(system_path)
    return candidates


def find_ffmpeg(configured: str = "") -> Optional[str]:
    """Return the path of a working ffmpeg, or None when none can be run."""
    global _cached_version
    for candidate in _candidates(configured):
        if not os.path.isfile(candidate) and not shutil.which(candidate):
            continue
        if os.path.isfile(candidate) and not _make_executable(candidate):
            continue
        version = probe_version(candidate)
        if version:
            _cached_version = version
            return candidate
        logging.warning(f"[FFmpeg] '{candidate}' exists but could not be executed")
    return None


def get_ffmpeg(configured: str = "") -> str:
    """Cached lookup. Raises FFmpegNotFoundError with a helpful message."""
    global _cached_path
    with _lock:
        if _cached_path and os.path.isfile(_cached_path):
            return _cached_path
        path = find_ffmpeg(configured)
        if not path:
            raise FFmpegNotFoundError(not_found_message())
        _cached_path = path
        source = (
            "bot folder"
            if os.path.dirname(os.path.abspath(path)) == os.path.abspath(app_vars.directory)
            else "system"
        )
        logging.info(f"[FFmpeg] Using {source} ffmpeg: {path} ({_cached_version})")
        return path


def get_version() -> str:
    return _cached_version


def reset_cache() -> None:
    global _cached_path, _cached_version
    with _lock:
        _cached_path = None
        _cached_version = ""


def not_found_message() -> str:
    return (
        "FFmpeg was not found. Install it system-wide so that 'ffmpeg' works in a "
        "terminal, or place {name} in the bot folder, right beside TTMediaBot.py "
        "({folder}).".format(name=EXECUTABLE_NAME, folder=app_vars.directory)
    )
