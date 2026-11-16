"""Fail-fast stream handling, HLS-only ffmpeg options, no blocking of the audio pump,
no pre-warm thread churn and no runaway autoplay (the five findings of the 8 Nov 2026 log)."""
import subprocess
import threading
import time
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from bot import Bot
from bot.player import ffmpeg_engine as fe
from bot.player.autoplay_gate import AutoplayGate
from bot.player.enums import Mode, State, TrackType
from bot.player.track import REFRESH_MIN_INTERVAL_SECONDS, Track
from tests.test_live_streams import live_player

HLS_URL = (
    "https://rr4---sn-2uuxa3vh-ngbs.googlevideo.com/videoplayback/id/rQJoEpzKkNk.7/itag/91/"
    "source/yt_live_broadcast/live/1/playlist_type/DVR/file/index.m3u8"
)
WEBM_URL = (
    "https://rr1---sn-2uuxa3vh-ngbs.googlevideo.com/videoplayback?expire=1&itag=251"
    "&mime=audio%2Fwebm&source=youtube"
)
# live=1 and yt_live_broadcast also occur on live links that are NOT HLS
LIVE_NOT_HLS_URL = (
    "https://rr1---sn-2uuxa3vh-ngbs.googlevideo.com/videoplayback?itag=140"
    "&source=yt_live_broadcast&live=1&sq=12"
)
HLS_ONLY = ["-extension_picky", "-allowed_extensions", "-allowed_segment_extensions", "-reconnect_at_eof"]
ALL_HLS_OPTIONS = {"extension_picky", "allowed_extensions", "allowed_segment_extensions"}
HTTP_OPTIONS = {"user_agent", "headers", "reconnect", "reconnect_at_eof"}


class HlsOptionTests(TestCase):
    def setUp(self):
        self.engine = fe.FFmpegEngine("ffmpeg", fe.AudioSink())
        fe._HTTP_OPTIONS_CACHE["ffmpeg"] = set(HTTP_OPTIONS)
        fe._HLS_OPTIONS_CACHE["ffmpeg"] = set(ALL_HLS_OPTIONS)
        self.addCleanup(fe._HTTP_OPTIONS_CACHE.pop, "ffmpeg", None)
        self.addCleanup(fe._HLS_OPTIONS_CACHE.pop, "ffmpeg", None)

    def command(self, url, hls=None):
        return self.engine._build_command(fe._Request(url, None, None, hls), 0.0, 1.0)

    def test_hls_links_are_recognized_strictly(self):
        self.assertTrue(fe.is_hls_url(HLS_URL))
        self.assertTrue(fe.is_hls_url("https://manifest.googlevideo.com/api/manifest/hls_variant/expire/1/file/index.m3u8"))
        self.assertTrue(fe.is_hls_url("https://x.googlevideo.com/api/manifest/hls_playlist/expire/1"))
        for url in (WEBM_URL, LIVE_NOT_HLS_URL, "song.mp3", "https://x.test/a.mp3", "https://x.test/a.m3u8.mp3", "", None):
            with self.subTest(url=url):
                self.assertFalse(fe.is_hls_url(url))

    def test_an_hls_playlist_on_youtube_gets_all_hls_options_before_the_input(self):
        command = self.command(HLS_URL)
        for flag in HLS_ONLY:
            self.assertIn(flag, command)
            self.assertLess(command.index(flag), command.index("-i"))
        self.assertEqual(command[command.index("-extension_picky") + 1], "0")
        self.assertEqual(command[command.index("-allowed_extensions") + 1], "ALL")
        self.assertEqual(command[command.index("-allowed_segment_extensions") + 1], "ALL")
        self.assertEqual(command[command.index("-reconnect_at_eof") + 1], "1")

    def test_ordinary_songs_never_get_hls_options(self):
        # An HLS demuxer option on a WebM/MP3 input makes ffmpeg stop with "Option not found".
        for url in (WEBM_URL, LIVE_NOT_HLS_URL, "https://x.test/a.mp3", "song.mp3"):
            with self.subTest(url=url):
                command = self.command(url)
                for flag in HLS_ONLY:
                    self.assertNotIn(flag, command)

    def test_a_playlist_from_another_host_keeps_ffmpegs_security_check(self):
        command = self.command("https://radio.example.test/stream/index.m3u8")
        for flag in HLS_ONLY:
            self.assertNotIn(flag, command)

    def test_an_option_this_ffmpeg_does_not_list_is_left_out(self):
        # extension_picky exists in builds that do not have allowed_segment_extensions yet
        fe._HLS_OPTIONS_CACHE["ffmpeg"] = {"extension_picky", "allowed_extensions"}
        command = self.command(HLS_URL)
        self.assertIn("-extension_picky", command)
        self.assertNotIn("-allowed_segment_extensions", command)
        fe._HLS_OPTIONS_CACHE["ffmpeg"] = set()  # the query failed or an old build: pass none
        fe._HTTP_OPTIONS_CACHE["ffmpeg"] = {"user_agent"}
        command = self.command(HLS_URL)
        for flag in HLS_ONLY:
            self.assertNotIn(flag, command)

    def test_the_caller_can_say_explicitly_whether_it_is_hls(self):
        self.assertIn("-extension_picky", self.command(WEBM_URL, hls=True))
        self.assertNotIn("-extension_picky", self.command(HLS_URL, hls=False))

    def test_the_options_of_the_hls_demuxer_are_read_from_ffmpeg(self):
        fe._HLS_OPTIONS_CACHE.pop("ffmpeg", None)
        text = (
            b"Demuxer hls [Apple HTTP Live Streaming]:\n"
            b"hls demuxer AVOptions:\n"
            b"  -live_start_index  <int>  .D......... segment index (default -3)\n"
            b"  -extension_picky   <boolean> .D......... Be picky (default true)\n"
            b"  -allowed_segment_extensions <string> .D......... List of file extensions\n"
        )
        done = subprocess.CompletedProcess([], 0, stdout=text)
        with patch("bot.player.ffmpeg_engine.subprocess.run", return_value=done) as run:
            names = fe._supported_hls_options("ffmpeg")
            fe._supported_hls_options("ffmpeg")  # cached
        self.assertEqual(names, {"live_start_index", "extension_picky", "allowed_segment_extensions"})
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][-2:], ["-h", "demuxer=hls"])


class RetryThreadTests(TestCase):
    def test_the_retry_never_blocks_the_thread_that_reports_the_end(self):
        player = live_player(last_position=900.0)
        started, release, played = threading.Event(), threading.Event(), threading.Event()
        seen = {}

        def slow_refresh():
            seen["thread"] = threading.current_thread()
            started.set()
            release.wait(5)  # the Node.js bridge answering slowly
            return "https://fresh.test/live.m3u8"

        player.track.refresh_stream = Mock(side_effect=slow_refresh)
        player._play = Mock(side_effect=lambda *a, **k: played.set())
        began = time.monotonic()
        player.on_end_file("eof")  # what the FFmpegPump thread calls
        self.assertLess(time.monotonic() - began, 1.0)
        self.assertTrue(started.wait(5))
        self.assertIsNot(seen["thread"], threading.current_thread())
        self.assertEqual(seen["thread"].name, "StreamRetry")
        self.assertTrue(seen["thread"].daemon)
        release.set()
        self.assertTrue(played.wait(5))

    def test_a_retry_that_finishes_after_the_user_moved_on_is_dropped(self):
        player = live_player(last_position=900.0)

        def refresh():
            player._play_token += 1  # the user started something else during the slow bridge call
            return "https://fresh.test/live.m3u8"

        player.track.refresh_stream = Mock(side_effect=refresh)
        from tests.inline_timer import inline_timers

        with inline_timers():
            player.on_end_file("eof")
        player._play.assert_not_called()
        player.stop.assert_not_called()
        player.bot.ttclient.send_message.assert_not_called()


class RefreshCooldownTests(TestCase):
    def make_track(self, fetched_ago):
        track = Track(service="yt", url="https://www.youtube.com/watch?v=abc", name="x",
                      type=TrackType.Dynamic, extra_info={"videoId": "abc"})
        track._original_track = Track(service="yt", url="https://www.youtube.com/watch?v=abc", name="x",
                                      type=TrackType.Dynamic, extra_info={"videoId": "abc"})
        track._last_stream_fetch_at = time.monotonic() - fetched_ago
        service = SimpleNamespace(
            _bridge=Mock(),
            get=Mock(return_value=[Track(service="yt", url="https://fresh.test/a", name="x",
                                         type=TrackType.Default, extra_info={"videoId": "abc"})]),
        )
        return track, service

    def refresh(self, track, service):
        with patch("builtins.get_service_by_name", return_value=service, create=True), \
                patch("bot.player.track.time.sleep") as sleep:
            track.refresh_stream()
        return sleep

    def test_a_link_asked_for_a_moment_ago_waits_before_the_next_one(self):
        track, service = self.make_track(fetched_ago=0.5)
        sleep = self.refresh(track, service)
        self.assertEqual(sleep.call_count, 1)
        self.assertAlmostEqual(sleep.call_args.args[0], REFRESH_MIN_INTERVAL_SECONDS - 0.5, delta=0.3)

    def test_an_old_link_is_refreshed_without_waiting(self):
        track, service = self.make_track(fetched_ago=9000.0)
        self.assertEqual(self.refresh(track, service).call_count, 0)

    def test_a_track_that_was_never_fetched_does_not_wait(self):
        track, service = self.make_track(fetched_ago=0.0)
        track._last_stream_fetch_at = 0.0
        self.assertEqual(self.refresh(track, service).call_count, 0)


class PreWarmThreadTests(TestCase):
    def make_bot(self, **services):
        bot = object.__new__(Bot)
        bot.service_manager = SimpleNamespace(services=services)
        bot._pre_warm_thread = None
        return bot

    def service(self, warmed, enabled=True):
        return SimpleNamespace(is_enabled=enabled, _is_warmed=warmed, _pre_warm=Mock())

    def test_no_thread_is_created_when_every_service_is_warm(self):
        bot = self.make_bot(yt=self.service(True), ytm=self.service(True))
        with patch("bot.threading.Thread") as thread:
            for _ in range(5):
                bot._start_periodic_pre_warm()
        thread.assert_not_called()

    def test_a_service_that_is_not_warm_yet_gets_one_thread_at_a_time(self):
        bot = self.make_bot(yt=self.service(True), ytm=self.service(False))
        with patch("bot.threading.Thread") as thread:
            thread.return_value.is_alive.return_value = True
            bot._start_periodic_pre_warm()
            bot._start_periodic_pre_warm()  # the first one is still running
        self.assertEqual(thread.call_count, 1)
        thread.return_value.start.assert_called_once_with()

    def test_a_disabled_service_is_not_warmed_and_does_not_raise(self):
        bot = self.make_bot(yt=self.service(False, enabled=False), ytm=self.service(True))
        self.assertEqual(bot._services_needing_pre_warm(), [])

    def test_the_cycle_only_warms_the_services_that_need_it(self):
        warm, cold = self.service(True), self.service(False)
        bot = self.make_bot(yt=warm, ytm=cold)
        bot._perform_periodic_pre_warm()
        warm._pre_warm.assert_not_called()
        cold._pre_warm.assert_called_once_with()


class AutoplayGateTests(TestCase):
    def test_a_burst_of_requests_becomes_one_fetch_for_the_last_video(self):
        fetched = []
        gate = AutoplayGate(lambda: True, delay=0.1, min_interval=0.0)
        for video_id in ("a", "b", "c", "d"):  # skipping n, n, n, n
            gate.request(fetched.append, video_id)
        time.sleep(0.5)
        self.assertEqual(fetched, ["d"])

    def test_a_second_burst_right_after_a_fetch_waits_for_the_minimum_interval(self):
        fetched = []
        gate = AutoplayGate(lambda: True, delay=0.05, min_interval=0.6)
        gate.request(fetched.append, "a")
        time.sleep(0.3)
        gate.request(fetched.append, "b")
        time.sleep(0.2)
        self.assertEqual(fetched, ["a"])  # b is held back
        time.sleep(0.6)
        self.assertEqual(fetched, ["a", "b"])

    def test_nothing_is_fetched_when_the_list_was_refilled_meanwhile(self):
        fetched = []
        gate = AutoplayGate(lambda: False, delay=0.05, min_interval=0.0)
        gate.request(fetched.append, "a")
        time.sleep(0.3)
        self.assertEqual(fetched, [])

    def test_the_fetch_runs_on_its_own_thread_and_a_failure_does_not_kill_the_gate(self):
        threads, fetched = [], []

        def boom(video_id):
            threads.append(threading.current_thread())
            raise RuntimeError("bridge down")

        gate = AutoplayGate(lambda: True, delay=0.05, min_interval=0.0)
        gate.request(boom, "a")
        time.sleep(0.3)
        gate.request(fetched.append, "b")
        time.sleep(0.3)
        self.assertIsNot(threads[0], threading.current_thread())
        self.assertEqual(fetched, ["b"])

    def test_cancel_drops_a_pending_request(self):
        fetched = []
        gate = AutoplayGate(lambda: True, delay=0.2, min_interval=0.0)
        gate.request(fetched.append, "a")
        gate.cancel()
        time.sleep(0.5)
        self.assertEqual(fetched, [])


class PlayerAutoplayTests(TestCase):
    def make_player(self, tracks=1, index=0):
        from bot.player import Player

        player = object.__new__(Player)
        player.track_list = [Track(service="yt", url="u", name=str(i), extra_info={"videoId": f"v{i:02d}"}) for i in range(tracks)]
        player.track_index = index
        player.track = player.track_list[index]
        player.mode = Mode.TrackList
        player.is_playlist = False
        player.autoplay_gate = Mock()
        service = SimpleNamespace(name="yt", _fetch_autoplay_sync=Mock())
        player.bot = SimpleNamespace(service_manager=SimpleNamespace(
            service=service, get_service_by_name=lambda name: service))
        return player, service

    def test_few_tracks_left_ask_the_gate_instead_of_fetching(self):
        player, service = self.make_player(tracks=3, index=1)
        player._check_and_trigger_autoplay()
        player.autoplay_gate.request.assert_called_once_with(service._fetch_autoplay_sync, "v01")
        service._fetch_autoplay_sync.assert_not_called()

    def test_a_long_list_does_not_ask_at_all(self):
        player, _ = self.make_player(tracks=30, index=2)
        player._check_and_trigger_autoplay()
        player.autoplay_gate.request.assert_not_called()

    def test_playlists_and_single_track_mode_are_left_alone(self):
        player, _ = self.make_player(tracks=3, index=1)
        player.is_playlist = True
        self.assertFalse(player.autoplay_needed())
        player.is_playlist, player.mode = False, Mode.SingleTrack
        self.assertFalse(player.autoplay_needed())
