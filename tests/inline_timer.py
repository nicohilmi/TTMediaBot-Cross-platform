"""Helper for the player tests: a stand-in for ``threading.Timer`` that runs at once.

The player starts every stream retry through ``threading.Timer`` (a thread of its own), so that
the audio pump is never blocked by the YouTube bridge. Most tests only care about *what* the retry
does, so they use ``inline_timers()``: the callback runs when the timer is started, on the calling
thread, and the delay that was asked for is recorded. That the retry really leaves the calling
thread is checked separately, with a real timer (tests/test_failfast_and_hls.py).
"""
from contextlib import contextmanager
from unittest.mock import patch


@contextmanager
def inline_timers():
    delays = []

    class InlineTimer:
        def __init__(self, interval, function, args=(), kwargs=None):
            self.interval = interval
            self.function = function
            self.args = args
            self.kwargs = kwargs or {}
            self.daemon = False
            self.name = ""

        def start(self):
            delays.append(self.interval)
            self.function(*self.args, **self.kwargs)

        def cancel(self):
            pass

    with patch("bot.player.threading.Timer", InlineTimer):
        yield delays
