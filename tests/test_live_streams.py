"""Live broadcasts of YouTube (a TV channel, an event, a 24/7 stream) on the yt service.

The bridge hands FFmpeg an HLS playlist for a broadcast. What happens in Python is checked here:
the service recognizes the live page of a channel, a broadcast is never replaced by another
search result, and the player keeps a broadcast going when the connection drops, while a
broadcast that is over is reported and left.
"""
import time
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from bot.player import LIVE_STREAM_HEALTHY_SECONDS, LIVE_STREAM_RETRY_DELAYS, Player
from bot.player.enums import Mode, State, TrackType
from bot.services.yt import YtService, is_channel_live_url


class ChannelLiveUrlTests(TestCase):
    def test_the_live_page_of_a_channel_is_recognized(self):
        for url in (
            "https://www.youtube.com/@KompasTV/live",
            "https://youtube.com/@KompasTV/live/",
            "https://m.youtube.com/channel/UCabcdefghijklmnopqrstuv/live",
            "https://www.youtube.com/c/SomeName/live?feature=share",
            "https://www.youtube.com/user/somebody/live",
            "  https://www.youtube.com/@KompasTV/live  ",
        ):
            with self.subTest(url=url):
                self.assertTrue(is_channel_live_url(url))

    def test_other_links_are_not_the_live_page_of_a_channel(self):
        for url in (
            "https://www.youtube.com/live/dQw4w9WgXcQ",
            "https://www.youtube.com/@KompasTV",
            "https://www.youtube.com/@KompasTV/videos",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://example.com/@x/live",
            "kompas tv live",
            "",
            None,
        ):
            with self.subTest(url=url):
                self.assertFalse(is_channel_live_url(url))


class YtServiceLiveTests(TestCase):
    def setUp(self):
        self.service = object.__new__(YtService)
        self.service.name = "yt"
        self.service.config = SimpleNamespace(search_results=1)
        self.service.bot = SimpleNamespace(
            translator=SimpleNamespace(translate=lambda value: value),
            player=SimpleNamespace(is_playlist=False),
        )
        self.service._bridge = Mock()
        self.service._fetch_autoplay_async = Mock()

    def get(self, url):
        return self.service._get_inner(url, None, False, time.perf_counter())

    def test_the_live_page_of_a_channel_is_one_video_not_a_playlist(self):
        self.service._bridge.info.return_value = {
            "id": "dQw4w9WgXcQ",
            "title": "KOMPAS TV LIVE",
            "uploader": "KOMPASTV",
            "is_live": True,
            "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        }
        tracks = self.get("https://www.youtube.com/@KompasTV/live")
        self.service._bridge.playlist.assert_not_called()
        self.service._bridge.info.assert_called_once_with(url="https://www.youtube.com/@KompasTV/live")
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].name, "KOMPAS TV LIVE - KOMPASTV")
        self.assertEqual(tracks[0].type, TrackType.Dynamic)  # the stream is looked up when it is played
        self.assertEqual(tracks[0]._url, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")  # not fetched yet

    def test_the_uploads_of_a_channel_are_still_a_playlist(self):
        self.service._bridge.playlist.return_value = {"title": "Uploads", "uploader": "x", "entries": []}
        self.get("https://www.youtube.com/@KompasTV")
        self.service._bridge.playlist.assert_called_once()
        self.service._bridge.info.assert_not_called()

    def test_a_resolved_broadcast_is_a_live_track(self):
        self.service._bridge.resolve.return_value = {
            "url": "https://manifest.googlevideo.com/api/manifest/hls_playlist/expire/1900000000/itag/91/index.m3u8",
            "title": "KOMPAS TV LIVE",
            "uploader": "KOMPASTV",
            "id": "dQw4w9WgXcQ",
            "is_live": True,
            "format": "hls",
        }
        tracks = self.service._get_inner("", {"videoId": "dQw4w9WgXcQ"}, True, time.perf_counter())
        self.assertEqual(tracks[0].type, TrackType.Live)
        self.assertTrue(tracks[0].url.endswith("index.m3u8"))

    def test_a_search_for_a_broadcast_keeps_it_even_when_the_title_looks_like_a_long_upload(self):
        entry = {"id": "x", "videoId": "x", "title": "NON STOP 24 JAM", "is_live": True}
        self.assertEqual(self.service._prefer_single_track("lofi 24/7", 1, [entry]), [entry])


def live_player(retries_done=0, last_position=0.0, requested=True, state=State.Playing):
    player = object.__new__(Player)
    track = SimpleNamespace(
        service="yt",
        name="KOMPAS TV LIVE",
        type=TrackType.Live,
        _stream_refresh_attempted=retries_done > 0,
        _stream_retry_count=retries_done,
    )

    def refresh():
        return "https://fresh.test/live.m3u8"

    track.refresh_stream = Mock(side_effect=refresh)
    player.track = track
    player._requested_track = track if requested else None
    player._play_token = 7
    player._fading_out = False
    player.state = state
    player.mode = Mode.TrackList
    player.queue = SimpleNamespace(is_empty=True)
    player._engine = SimpleNamespace(idle=True, last_position=last_position)
    player._play = Mock()
    player.stop = Mock()
    player.next = Mock()
    player.bot = SimpleNamespace(
        translator=SimpleNamespace(translate=lambda text: text),
        ttclient=SimpleNamespace(send_message=Mock()),
    )
    return player


class PlayerLiveStreamTests(TestCase):
    def test_the_schedule_starts_at_once_and_waits_longer_than_for_a_song(self):
        self.assertEqual(LIVE_STREAM_RETRY_DELAYS[0], 0.0)
        self.assertGreater(len(LIVE_STREAM_RETRY_DELAYS), 3)
        self.assertTrue(all(delay > 0 for delay in LIVE_STREAM_RETRY_DELAYS[1:]))

    def test_a_broadcast_that_stops_normally_is_picked_up_again_not_skipped(self):
        player = live_player(last_position=900.0)
        player.on_end_file("eof")
        player.track.refresh_stream.assert_called_once_with()
        player._play.assert_called_once()
        player.next.assert_not_called()
        player.stop.assert_not_called()

    def test_a_broadcast_never_resumes_at_an_old_position(self):
        player = live_player(last_position=5000.0)
        player.on_end_file("error", "HTTP error 403 Forbidden")
        self.assertEqual(player._play.call_args.kwargs["start_position"], 0.0)
        self.assertTrue(player._play.call_args.kwargs["is_refresh"])

    def test_a_broadcast_that_played_for_a_while_starts_a_new_count(self):
        # six interruptions were used up earlier today; this one is a new interruption
        player = live_player(retries_done=len(LIVE_STREAM_RETRY_DELAYS), last_position=LIVE_STREAM_HEALTHY_SECONDS + 1)
        player.on_end_file("error", "connection reset")
        player.track.refresh_stream.assert_called_once_with()
        self.assertEqual(player.track._stream_retry_count, 1)

    def test_a_broadcast_that_keeps_failing_at_once_is_given_up_after_the_last_delay(self):
        player = live_player(retries_done=len(LIVE_STREAM_RETRY_DELAYS), last_position=2.0)
        player.on_end_file("error", "HTTP error 403 Forbidden")
        player.track.refresh_stream.assert_not_called()
        player.stop.assert_called_once_with()  # the one the person asked for is not replaced by another
        player.bot.ttclient.send_message.assert_called_once()

    @patch("bot.player.threading.Timer")
    def test_later_retries_wait_for_their_delay(self, timer):
        player = live_player(retries_done=3, last_position=0.0)
        player.on_end_file("error", "")
        self.assertEqual(timer.call_args.args[0], LIVE_STREAM_RETRY_DELAYS[3])
        player._play.assert_not_called()

    def test_a_broadcast_that_is_over_is_reported_and_left(self):
        player = live_player(last_position=300.0)

        def refresh():
            player.track.type = TrackType.Default  # the link now leads to the recording
            return "https://fresh.test/recording"

        player.track.refresh_stream = Mock(side_effect=refresh)
        player.on_end_file("eof")
        player._play.assert_not_called()
        player.next.assert_called_once_with()
        text = player.bot.ttclient.send_message.call_args.args[0]
        self.assertEqual(text, 'The live stream "KOMPAS TV LIVE" has ended.')

    @patch("bot.player.threading.Timer")
    def test_a_broadcast_that_cannot_be_reached_for_a_moment_is_asked_for_again(self, timer):
        player = live_player(last_position=300.0)
        player.track.refresh_stream = Mock(side_effect=RuntimeError("bridge down"))
        player.on_end_file("eof")
        # the first retry was immediate and failed; the next one waits for its delay
        self.assertEqual(timer.call_args.args[0], LIVE_STREAM_RETRY_DELAYS[1])
        player.stop.assert_not_called()
        player.next.assert_not_called()

    def test_a_song_that_ends_normally_still_goes_on_to_the_next_track(self):
        player = live_player(last_position=300.0)
        player.track.type = TrackType.Default
        player.on_end_file("eof")
        player.track.refresh_stream.assert_not_called()
        player.next.assert_called_once_with()

    def test_a_live_track_is_not_seekable(self):
        player = live_player()
        self.assertFalse(player._is_seekable_source())
