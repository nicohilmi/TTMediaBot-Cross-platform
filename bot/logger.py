from __future__ import annotations

import atexit
import collections
from enum import Flag
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import threading
from typing import TYPE_CHECKING, Any, Deque, List, Optional

if TYPE_CHECKING:
    from bot import Bot


PLAYER_DEBUG_LEVEL = 5
# How many records may wait for the real handlers (see install_bootstrap_logging).
EARLY_BUFFER_CAPACITY = 1000


class Mode(Flag):
    STDOUT = 1
    FILE = 2
    STDOUT_AND_FILE = STDOUT | FILE


class _EarlyBuffer(logging.Handler):
    """Keeps records that are emitted before the real handlers exist.

    Why this exists: the python-mpv event thread starts inside Bot.__init__ and calls
    logging.log() long before initialize_logger() runs. The first module-level
    logging.*() call on a root logger without handlers triggers an implicit
    logging.basicConfig(), which attaches a console handler. After that every later
    basicConfig() call is a silent no-op, so the log file stayed empty and everything
    went to the console. This buffer occupies the root logger from the very first
    import so that never happens, and nothing emitted early is lost.
    """

    def __init__(self, capacity: int = EARLY_BUFFER_CAPACITY) -> None:
        super().__init__(level=logging.NOTSET)
        self.records: Deque[logging.LogRecord] = collections.deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # Freeze the final text now so later mutation of the arguments cannot change it.
            record.msg = record.getMessage()
            record.args = None
        except Exception:
            pass
        self.records.append(record)


_early_buffer: Optional[_EarlyBuffer] = None
_hooks_installed = False
_console_logging = False


def _flush_early_buffer_at_exit() -> None:
    # The program ended (a config or FFmpeg error, for example) before logging was
    # configured: show the waiting warnings instead of losing them.
    release_bootstrap()


def install_bootstrap_logging() -> None:
    """Call as early as possible (bot/__init__.py does it on import)."""
    global _early_buffer
    if _early_buffer is not None:
        return
    logging.addLevelName(PLAYER_DEBUG_LEVEL, "PLAYER_DEBUG")
    root = logging.getLogger()
    _early_buffer = _EarlyBuffer()
    root.addHandler(_early_buffer)
    if root.level == logging.NOTSET or root.level > logging.DEBUG:
        root.setLevel(logging.DEBUG)
    atexit.register(_flush_early_buffer_at_exit)


def release_bootstrap(handlers: Optional[List[logging.Handler]] = None) -> None:
    """Detach the early buffer and replay what it caught.

    handlers: the real handlers (already attached to the root logger by the caller).
    None means no logging was configured (log disabled or --devices): the records are
    replayed to the console at WARNING and above, like Python does by default.
    """
    global _early_buffer
    buffer, _early_buffer = _early_buffer, None
    if buffer is None:
        return
    root = logging.getLogger()
    root.removeHandler(buffer)
    if handlers is None:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.WARNING)
        console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        root.addHandler(console_handler)
        root.setLevel(logging.WARNING)
        handlers = [console_handler]
    for record in list(buffer.records):
        for handler in handlers:
            if record.levelno >= handler.level:
                handler.handle(record)
    buffer.records.clear()
    buffer.close()


def _resolve_log_file(bot: Bot) -> str:
    if bot.log_file_name:
        file_name = bot.log_file_name
    else:
        file_name = bot.config.logger.file_name
    directory = os.path.dirname(file_name)
    if directory and os.path.isdir(directory):
        return file_name
    return os.path.join(bot.config_manager.config_dir, file_name)


def _install_exception_hooks() -> None:
    """Send errors that nobody catches to the log instead of only to the console."""
    global _hooks_installed
    if _hooks_installed:
        return
    _hooks_installed = True
    previous_excepthook = sys.excepthook

    def excepthook(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            previous_excepthook(exc_type, exc_value, exc_traceback)
            return
        logging.critical(
            "Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback)
        )
        if not _console_logging:
            # A crash should still be visible where the bot was started.
            previous_excepthook(exc_type, exc_value, exc_traceback)

    sys.excepthook = excepthook

    if hasattr(threading, "excepthook"):

        def thread_excepthook(args):
            if args.exc_type is SystemExit:
                return
            thread_name = args.thread.name if args.thread is not None else "unknown"
            logging.error(
                "Unhandled exception in thread %s",
                thread_name,
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )

        threading.excepthook = thread_excepthook

    if hasattr(sys, "unraisablehook"):

        def unraisablehook(unraisable):
            try:
                description = "{}: {!r}".format(
                    unraisable.err_msg or "Unraisable exception", unraisable.object
                )
            except Exception:
                description = "Unraisable exception"
            logging.error(
                description,
                exc_info=(
                    unraisable.exc_type,
                    unraisable.exc_value,
                    unraisable.exc_traceback,
                ),
            )

        sys.unraisablehook = unraisablehook


def initialize_logger(bot: Bot) -> None:
    global _console_logging
    config = bot.config.logger
    logging.addLevelName(PLAYER_DEBUG_LEVEL, "PLAYER_DEBUG")
    level = logging.getLevelName(config.level)
    if not isinstance(level, int):
        sys.exit("Invalid log level name")
    formatter = logging.Formatter(config.format)
    handlers: List[Any] = []
    try:
        mode = (
            Mode(config.mode)
            if isinstance(config.mode, int)
            else Mode.__members__[config.mode]
        )
    except (KeyError, ValueError):
        sys.exit("Invalid log mode name")
    log_file = ""
    if mode & Mode.FILE == Mode.FILE:
        log_file = _resolve_log_file(bot)
        try:
            rotating_file_handler = RotatingFileHandler(
                filename=log_file,
                mode="a",
                maxBytes=config.max_file_size * 1024,
                backupCount=config.backup_count,
                encoding="UTF-8",
            )
        except OSError as e:
            # Never leave the bot without any log: fall back to the console.
            print(
                "Cannot open the log file {}: {}. Logging to the console instead.".format(
                    log_file, e
                ),
                file=sys.stderr,
            )
            mode |= Mode.STDOUT
            log_file = ""
        else:
            rotating_file_handler.setFormatter(formatter)
            rotating_file_handler.setLevel(level)
            handlers.append(rotating_file_handler)
    if mode & Mode.STDOUT == Mode.STDOUT:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(level)
        handlers.append(stream_handler)
    _console_logging = mode & Mode.STDOUT == Mode.STDOUT

    # Configure the root logger directly instead of logging.basicConfig(): basicConfig
    # does nothing when the root logger already has a handler, which is exactly what
    # used to leave the log file empty.
    root = logging.getLogger()
    for old_handler in list(root.handlers):
        if old_handler is not _early_buffer:
            root.removeHandler(old_handler)
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level)
    release_bootstrap(handlers)

    logging.captureWarnings(True)
    _install_exception_hooks()
    logging.info(
        "Logger initialized: level=%s, mode=%s, file=%s",
        config.level,
        mode.name if mode.name else str(mode),
        log_file or "-",
    )
