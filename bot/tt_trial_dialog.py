"""Close the TeamTalk SDK "Trial expired" message box automatically (Windows).

The trial build of ``TeamTalk5.dll`` shows a modal Windows message box titled
"Trial expired" when its trial period is over. The box blocks the thread that
called into the DLL until somebody presses OK, which makes every start and every
restart (the ``rs`` command) wait for a manual click.

This module starts a small background thread that looks for that one message box
among the windows of *this* process and presses its OK button, exactly like a user
would. Nothing in the SDK is patched and the SDK's trial/licence state is not
changed: the DLL still reports itself as an expired trial.

``start()`` must run before ``TeamTalk5.dll`` is loaded (``bot/__init__.py`` calls
it before importing ``bot.TeamTalk``). It does nothing on non-Windows platforms.

Set the environment variable ``TTMEDIABOT_KEEP_SDK_DIALOG=1`` to switch it off.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time
from ctypes import wintypes
from typing import Any, Dict, Iterator, Optional, Set

DISABLE_ENV_VAR = "TTMEDIABOT_KEEP_SDK_DIALOG"

# Standard Windows message box (dialog class) and the title the SDK gives it.
DIALOG_CLASS = "#32770"
DIALOG_TITLE = "Trial expired"
BUTTON_CLASS = "Button"

POLL_INTERVAL = 0.1  # seconds between looks for the message box
CLICK_ATTEMPTS = 3  # tries with the OK button before the window is closed instead

BM_CLICK = 0x00F5
WM_COMMAND = 0x0111
WM_CLOSE = 0x0010
IDOK = 1

_start_lock = threading.Lock()
_started = False


def _load_user32() -> Any:
    # A private WinDLL instance, so the argtypes set here never leak into other
    # code that uses ctypes.windll.user32.
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.FindWindowExW.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
    ]
    user32.FindWindowExW.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.PostMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.PostMessageW.restype = wintypes.BOOL
    return user32


def _window_pid(user32: Any, hwnd: int) -> int:
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def find_own_dialogs(user32: Any, pid: int) -> Iterator[int]:
    """Yield every "Trial expired" message box that belongs to process ``pid``.

    Other programs (or other bots running at the same time) may show a box with
    the same title; those are left to their own process.
    """
    hwnd: Optional[int] = None
    while True:
        hwnd = user32.FindWindowExW(None, hwnd, DIALOG_CLASS, DIALOG_TITLE)
        if not hwnd:
            return
        if _window_pid(user32, hwnd) == pid:
            yield hwnd


def dismiss(user32: Any, hwnd: int, attempt: int) -> None:
    """Press OK on the message box; fall back to closing it if it stays open."""
    if attempt >= CLICK_ATTEMPTS:
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        return
    button = user32.FindWindowExW(hwnd, None, BUTTON_CLASS, None)
    if button:
        user32.PostMessageW(button, BM_CLICK, 0, 0)
    else:
        user32.PostMessageW(hwnd, WM_COMMAND, IDOK, 0)


def _watch() -> None:
    try:
        user32 = _load_user32()
    except Exception:
        logging.debug("SDK trial dialog guard could not load user32", exc_info=True)
        return
    pid = os.getpid()
    attempts: Dict[int, int] = {}
    while True:
        try:
            seen: Set[int] = set()
            for hwnd in find_own_dialogs(user32, pid):
                seen.add(hwnd)
                attempt = attempts.get(hwnd, 0)
                if attempt == 0:
                    logging.info(
                        "TeamTalk SDK 'Trial expired' window closed automatically"
                    )
                dismiss(user32, hwnd, attempt)
                attempts[hwnd] = attempt + 1
            for gone in set(attempts) - seen:
                del attempts[gone]
        except Exception:
            # The guard must never take the bot down.
            logging.debug("SDK trial dialog guard error", exc_info=True)
        time.sleep(POLL_INTERVAL)


def start() -> None:
    """Start the background watcher once per process (Windows only)."""
    global _started
    if sys.platform != "win32" or os.environ.get(DISABLE_ENV_VAR):
        return
    with _start_lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_watch, name="sdk-trial-dialog-guard", daemon=True).start()
