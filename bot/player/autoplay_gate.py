"""Keeps the autoplay (recommendation) fetches from running away.

Autoplay adds ~15 recommended songs to the track list whenever few songs are left. It used to be
triggered by every track change, so skipping quickly (n, n, n) started one fetch per skip, each for
a different video, and the list grew from 16 to 76 songs. The gate puts three limits on it:

* debounce: a burst of requests becomes ONE fetch, for the last video, once the burst is over;
* one at a time, and at least ``min_interval`` seconds between the starts of two fetches;
* the fetch only runs if the list still needs songs at that moment (``still_needed``), so a list
  that has just been refilled is left alone.

The fetch itself runs on a timer thread, never on the caller's (the player or the audio pump).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

# Quiet time that ends a burst of requests (rapid skipping).
AUTOPLAY_DEBOUNCE_SECONDS = 1.5
# Shortest time between the starts of two fetches. The refill of one fetch lasts for many songs,
# so a second one sooner than this is never useful.
AUTOPLAY_MIN_INTERVAL_SECONDS = 20.0
# Autoplay refills the list when this many songs or fewer are left after the current one.
AUTOPLAY_REFILL_THRESHOLD = 4


class AutoplayGate:
    def __init__(
        self,
        still_needed: Callable[[], bool],
        delay: float = AUTOPLAY_DEBOUNCE_SECONDS,
        min_interval: float = AUTOPLAY_MIN_INTERVAL_SECONDS,
    ) -> None:
        self._still_needed = still_needed
        self._delay = delay
        self._min_interval = min_interval
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._pending: Optional[tuple] = None  # (fetch, video_id) of the newest request
        self._running = False
        self._last_start = float("-inf")

    def request(self, fetch: Callable[[str], object], video_id: str) -> None:
        """Ask for an autoplay fetch. Returns at once; the newest request wins."""
        with self._lock:
            self._pending = (fetch, video_id)
            self._arm(self._delay)

    def cancel(self) -> None:
        with self._lock:
            self._pending = None
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    # The lock is held by the caller of the two methods below.
    def _arm(self, delay: float) -> None:
        if self._timer is not None:
            self._timer.cancel()
        wait = max(delay, self._last_start + self._min_interval - time.monotonic())
        timer = threading.Timer(wait, self._fire)
        timer.daemon = True
        timer.name = "AutoplayGate"
        self._timer = timer
        timer.start()

    def _fire(self) -> None:
        with self._lock:
            self._timer = None
            if self._pending is None:
                return
            if self._running:
                self._arm(1.0)  # the previous fetch is still going; look again shortly
                return
            fetch, video_id = self._pending
            self._pending = None
            self._running = True
            self._last_start = time.monotonic()
        try:
            if self._still_needed():
                fetch(video_id)
            else:
                logging.debug("[Autoplay] enough songs are queued; fetch for %s skipped", video_id)
        except Exception:
            logging.error("[Autoplay] fetch failed", exc_info=True)
        finally:
            with self._lock:
                self._running = False
