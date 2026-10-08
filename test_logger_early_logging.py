"""Regression tests for the logging mechanism (bot/logger.py).

The bug: Player.__init__ runs during Bot.__init__ and calls ffmpeg_locator.get_ffmpeg(),
which calls logging.info(). That happens before initialize_logger(). A logging.*() call on
a root logger without handlers runs an implicit logging.basicConfig(), after which the real
basicConfig() is a silent no-op: TTMediaBot.log stayed empty, warnings and errors went to
the console, and INFO lines were recorded nowhere (the root level was stuck at WARNING).

bot/logger.py is loaded straight from its file so these tests need neither the TeamTalk
library nor FFmpeg.
"""

import importlib.util
import io
import logging
import os
import sys
import tempfile
import threading
from contextlib import redirect_stderr
from types import SimpleNamespace
from unittest import TestCase

LOGGER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot", "logger.py")


def load_logger_module():
    spec = importlib.util.spec_from_file_location("ttbot_logger_under_test", LOGGER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LoggerTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = logging.getLogger()
        self.saved_handlers = list(self.root.handlers)
        self.saved_level = self.root.level
        self.saved_hooks = (sys.excepthook, threading.excepthook, sys.unraisablehook)
        for handler in list(self.root.handlers):
            self.root.removeHandler(handler)
        self.logger = load_logger_module()

    def tearDown(self):
        for handler in list(self.root.handlers):
            self.root.removeHandler(handler)
            handler.close()
        for handler in self.saved_handlers:
            self.root.addHandler(handler)
        self.root.setLevel(self.saved_level)
        sys.excepthook, threading.excepthook, sys.unraisablehook = self.saved_hooks
        logging.captureWarnings(False)
        self.tmp.cleanup()

    def make_bot(self, **overrides):
        config = dict(
            log=True,
            level="INFO",
            format="%(levelname)s: %(message)s",
            mode="FILE",
            file_name="TTMediaBot.log",
            max_file_size=0,
            backup_count=0,
        )
        config.update(overrides)
        return SimpleNamespace(
            config=SimpleNamespace(logger=SimpleNamespace(**config)),
            log_file_name=None,
            config_manager=SimpleNamespace(config_dir=self.tmp.name),
        )

    def read_log(self):
        with open(os.path.join(self.tmp.name, "TTMediaBot.log"), encoding="utf-8") as f:
            return f.read()

    def test_records_logged_before_initialization_reach_the_file(self):
        self.logger.install_bootstrap_logging()
        # What ffmpeg_locator.get_ffmpeg() does while Bot.__init__ is still running.
        logging.info("[FFmpeg] Using system ffmpeg: /usr/bin/ffmpeg (ffmpeg version 6.1)")
        logging.warning("early warning")

        self.logger.initialize_logger(self.make_bot())
        logging.info("later info")
        logging.error("later error")

        content = self.read_log()
        self.assertIn("INFO: [FFmpeg] Using system ffmpeg", content)
        self.assertIn("WARNING: early warning", content)
        self.assertIn("INFO: later info", content)
        self.assertIn("ERROR: later error", content)

    def test_stray_root_handler_no_longer_hijacks_the_log(self):
        # No bootstrap installed: the first logging.*() call adds a console handler,
        # exactly like the old implicit basicConfig().
        logging.info("[FFmpeg] Using system ffmpeg: /usr/bin/ffmpeg")
        self.assertTrue(self.root.handlers)

        self.logger.initialize_logger(self.make_bot())
        logging.info("must be in the file")

        self.assertIn("INFO: must be in the file", self.read_log())
        self.assertEqual(
            [h for h in self.root.handlers if type(h) is logging.StreamHandler], []
        )

    def test_unhandled_thread_exception_is_logged(self):
        self.logger.initialize_logger(self.make_bot())

        def crash():
            raise ValueError("boom in worker")

        thread = threading.Thread(target=crash, name="worker-under-test")
        thread.start()
        thread.join()

        content = self.read_log()
        self.assertIn("Unhandled exception in thread worker-under-test", content)
        self.assertIn("ValueError: boom in worker", content)

    def test_unhandled_main_exception_is_logged(self):
        self.logger.initialize_logger(self.make_bot())
        try:
            raise RuntimeError("fatal in main")
        except RuntimeError:
            exc_info = sys.exc_info()
        with redirect_stderr(io.StringIO()) as console:
            sys.excepthook(*exc_info)

        self.assertIn("RuntimeError: fatal in main", self.read_log())
        # FILE-only mode still shows a crash where the bot was started.
        self.assertIn("fatal in main", console.getvalue())

    def test_unwritable_log_file_falls_back_to_console(self):
        bot = self.make_bot()
        bot.config_manager.config_dir = os.path.join(self.tmp.name, "does", "not", "exist")
        with redirect_stderr(io.StringIO()) as console:
            self.logger.initialize_logger(bot)

        self.assertIn("Cannot open the log file", console.getvalue())
        self.assertTrue(
            any(type(h) is logging.StreamHandler for h in self.root.handlers)
        )

    def test_invalid_level_and_mode_exit_cleanly(self):
        with self.assertRaises(SystemExit):
            self.logger.initialize_logger(self.make_bot(level="NOPE"))
        with self.assertRaises(SystemExit):
            self.logger.initialize_logger(self.make_bot(mode="NOPE"))
        with self.assertRaises(SystemExit):
            self.logger.initialize_logger(self.make_bot(mode=7))

    def test_release_without_configuration_replays_warnings_only(self):
        self.logger.install_bootstrap_logging()
        logging.info("quiet info")
        logging.warning("loud warning")
        with redirect_stderr(io.StringIO()) as console:
            # The handler is created inside release_bootstrap(), after the redirect.
            self.logger.release_bootstrap()

        self.assertIn("loud warning", console.getvalue())
        self.assertNotIn("quiet info", console.getvalue())

    def test_warnings_are_not_lost_when_the_bot_exits_before_logging_is_ready(self):
        self.logger.install_bootstrap_logging()
        logging.warning("[FFmpeg] 'ffmpeg' exists but could not be executed")
        with redirect_stderr(io.StringIO()) as console:
            # What the atexit hook runs when e.g. FFmpegNotFoundError ends the program.
            self.logger._flush_early_buffer_at_exit()

        self.assertIn("could not be executed", console.getvalue())
