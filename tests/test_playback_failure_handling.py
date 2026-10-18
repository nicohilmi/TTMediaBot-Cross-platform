"""A YouTube stream that fails must never be replaced by another song in silence."""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from bot.player import Player, STREAM_RETRY_DELAYS
from bot.player.enums import Mode, State


def make_player(retries_done=0, requested=True, state=State.Playing):
    player = object.__new__(Player)
    track = SimpleNamespace(
        service="ytm",
        name="Bersenja Gurau",
        type=None,
        _stream_refresh_attempted=retries_done > 0,
        _stream_retry_count=retries_done,
        refresh_stream=Mock(return_value="https://fresh.test/audio"),
    )
    player.track = track
    player._requested_track = track if requested else None
    player._play_token = 7
    player._fading_out = False
    player.state = state
    player.mode = Mode.TrackList
    player.queue = SimpleNamespace(is_empty=True)
    player._engine = SimpleNamespace(idle=True, last_position=0.0)
    player._play = Mock()
    player.stop = Mock()
    player.next = Mock()
    player.bot = SimpleNamespace(
        translator=SimpleNamespace(translate=lambda text: text),
        ttclient=SimpleNamespace(send_message=Mock()),
    )
    return player


class StreamRetryScheduleTests(TestCase):
    def test_retry_delays_start_immediately_then_wait(self):
        self.assertEqual(STREAM_RETRY_DELAYS[0], 0.0)
        self.assertTrue(all(delay > 0 for delay in STREAM_RETRY_DELAYS[1:]))

    @patch("bot.player.threading.Timer")
    def test_second_failure_waits_instead_of_retrying_at_once(self, timer):
        player = make_player(retries_done=1)

        player.on_end_file("error", "HTTP error 403 Forbidden")

        timer.assert_called_once()
        self.assertEqual(timer.call_args.args[0], STREAM_RETRY_DELAYS[1])
        timer.return_value.start.assert_called_once_with()
        player._play.assert_not_called()
        player.next.assert_not_called()
        self.assertEqual(player.track._stream_retry_count, 2)

    @patch("bot.player.threading.Timer")
    def test_third_failure_waits_longer(self, timer):
        player = make_player(retries_done=2)

        player.on_end_file("error", "")

        self.assertEqual(timer.call_args.args[0], STREAM_RETRY_DELAYS[2])

    def test_scheduled_retry_refreshes_and_plays(self):
        player = make_player(retries_done=2)

        player._run_stream_retry(player.track, 0.0, 7)

        player.track.refresh_stream.assert_called_once_with()
        player._play.assert_called_once()

    def test_scheduled_retry_is_dropped_when_the_user_started_other_playback(self):
        player = make_player(retries_done=2)
        player._play_token = 8  # something else was started meanwhile

        player._run_stream_retry(player.track, 0.0, 7)

        player.track.refresh_stream.assert_not_called()
        player._play.assert_not_called()

    def test_scheduled_retry_is_dropped_after_stop(self):
        player = make_player(retries_done=2, state=State.Stopped)

        player._run_stream_retry(player.track, 0.0, 7)

        player._play.assert_not_called()


class GivingUpTests(TestCase):
    def test_requested_track_is_not_replaced_by_the_next_song(self):
        player = make_player(retries_done=len(STREAM_RETRY_DELAYS), requested=True)

        player.on_end_file("error", "HTTP error 403 Forbidden")

        player.stop.assert_called_once_with()
        player.next.assert_not_called()
        text = player.bot.ttclient.send_message.call_args.args[0]
        self.assertIn("Bersenja Gurau", text)
        self.assertIn("try again", text)

    def test_following_track_is_skipped_but_the_chat_is_told(self):
        player = make_player(retries_done=len(STREAM_RETRY_DELAYS), requested=False)

        player.on_end_file("error", "HTTP error 403 Forbidden")

        player.next.assert_called_once_with()
        player.stop.assert_not_called()
        text = player.bot.ttclient.send_message.call_args.args[0]
        self.assertIn("Skipping to the next track", text)

    def test_failing_refresh_gives_up_too(self):
        player = make_player(retries_done=1, requested=True)
        player.track.refresh_stream.side_effect = RuntimeError("bridge down")

        player._run_stream_retry(player.track, 0.0, 7)

        player.stop.assert_called_once_with()
        player.bot.ttclient.send_message.assert_called_once()

    def test_nothing_is_announced_when_the_user_already_stopped(self):
        player = make_player(retries_done=len(STREAM_RETRY_DELAYS), state=State.Stopped)

        player.on_end_file("error", "")

        player.bot.ttclient.send_message.assert_not_called()
        player.next.assert_not_called()

    def test_announcement_failure_does_not_break_playback_handling(self):
        player = make_player(retries_done=len(STREAM_RETRY_DELAYS), requested=True)
        player.bot.ttclient.send_message.side_effect = RuntimeError("not connected")

        player.on_end_file("error", "")

        player.stop.assert_called_once_with()
