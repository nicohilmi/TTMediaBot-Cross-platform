"""Concurrent autoplay fetches used to add the same recommendations twice or more."""
import logging
import threading
import time
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from bot.player.track import Track
from bot.services.yt import YtService
from bot.services.ytm import YtmService


def _entries(prefix, count=20):
    return [
        {"videoId": f"{prefix}{i:02d}", "id": f"{prefix}{i:02d}", "title": f"Song {i}", "uploader": "A"}
        for i in range(count)
    ]


class _SlowBridge:
    def __init__(self, entries):
        self.entries = entries
        self.calls = 0

    def recommendations(self, video_id, limit):
        self.calls += 1
        time.sleep(0.05)  # lets the other threads reach the merge at the same time
        return {"entries": list(self.entries)}


def _make(service_class, name):
    service = object.__new__(service_class)
    service.name = name
    track_list = [Track(service=name, url="u", name="first", extra_info={"videoId": "seed", "id": "seed"})]
    service.bot = SimpleNamespace(
        player=SimpleNamespace(track_index=0, track_list=track_list, _schedule_prefetch=lambda: None)
    )
    service._bridge = _SlowBridge(_entries("rec"))
    return service


def _ids(service):
    return [(t.extra_info or {}).get("videoId") or (t.extra_info or {}).get("id") for t in service.bot.player.track_list]


_real_info = logging.info


def _slow_info(message, *args, **kwargs):
    """The real bug: the "Adding N recommendations" log line sits between the duplicate
    check and the list update, and logging I/O lets another thread in at that point."""
    if "Adding" in str(message):
        time.sleep(0.05)
    return _real_info(message, *args, **kwargs)


class AutoplayRaceTests(TestCase):
    def _run_in_threads(self, service, video_ids, target=None):
        target = target or service._fetch_autoplay_sync
        with patch("logging.info", _slow_info):
            threads = [threading.Thread(target=target, args=(v,)) for v in video_ids]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)

    def test_the_race_is_real_without_the_lock(self):
        """Guards the guard: the unlocked merge really does duplicate songs here."""
        service = _make(YtService, "yt")
        self._run_in_threads(service, ["seed", "seed", "seed"], target=service._fetch_autoplay_unlocked)
        ids = _ids(service)
        self.assertGreater(len(ids), len(set(ids)))

    def test_yt_same_video_fetched_three_times_adds_each_song_once(self):
        service = _make(YtService, "yt")
        self._run_in_threads(service, ["seed", "seed", "seed"])
        ids = _ids(service)
        self.assertEqual(len(ids), len(set(ids)), f"duplicates in queue: {ids}")
        self.assertEqual(service._bridge.calls, 1)

    def test_yt_different_triggers_still_never_duplicate(self):
        service = _make(YtService, "yt")
        self._run_in_threads(service, ["seed", "other1", "other2"])
        ids = _ids(service)
        self.assertEqual(len(ids), len(set(ids)), f"duplicates in queue: {ids}")

    def test_ytm_same_video_fetched_three_times_adds_each_song_once(self):
        service = _make(YtmService, "ytm")
        service._get_recommendation_tracks = lambda video_id, limit: [
            Track(service="ytm", url="u", name=e["title"], extra_info=e)
            for e in service._bridge.recommendations(video_id, limit)["entries"]
        ]
        self._run_in_threads(service, ["seed", "seed", "seed"])
        ids = _ids(service)
        self.assertEqual(len(ids), len(set(ids)), f"duplicates in queue: {ids}")

    def test_inflight_marker_is_released_after_a_failure(self):
        service = _make(YtService, "yt")

        def boom(video_id, limit):
            raise RuntimeError("bridge down")

        service._bridge.recommendations = boom
        service._get_recommendations = lambda video_id, limit=20: []
        service._fetch_autoplay_sync("seed")
        self.assertNotIn("seed", YtService._autoplay_inflight)
