from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from bot.player import Player
from bot.player.enums import Mode, State
from tests.inline_timer import inline_timers


def make_player(last_position=0.0, state=State.Playing, attempted=False):
    player = object.__new__(Player)
    player.track = SimpleNamespace(
        service="ytm",
        name="Ela Vem",
        type=None,
        _stream_refresh_attempted=attempted,
        refresh_stream=Mock(return_value="https://fresh.test/audio"),
    )
    player.state = state
    player._play_token = 7
    player._fading_out = False
    player._requested_track = player.track
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


def retry_once(player, *args):
    """Plays on_end_file with ONE automatic retry allowed for ordinary tracks (the default is
    none) and the retry timer run inline. These tests check what a retry does."""
    with patch("bot.player.STREAM_RETRY_DELAYS", (0.0,)), inline_timers():
        player.on_end_file(*args)


class PlayerStreamRetryTests(TestCase):
    def test_error_refreshes_youtube_stream_once(self):
        player = make_player()

        retry_once(player, "error", "HTTP error 403 Forbidden")

        player.track.refresh_stream.assert_called_once_with()
        player._play.assert_called_once_with(
            "https://fresh.test/audio",
            save_to_recents=False,
            start_position=0.0,
            is_refresh=True,
        )
        self.assertTrue(player.track._stream_refresh_attempted)

    def test_refreshed_stream_resumes_where_playback_stopped(self):
        player = make_player(last_position=42.5)

        retry_once(player, "error", "")

        player._play.assert_called_once_with(
            "https://fresh.test/audio",
            save_to_recents=False,
            start_position=42.5,
            is_refresh=True,
        )

    def test_error_in_the_first_seconds_restarts_from_the_beginning(self):
        player = make_player(last_position=1.2)

        retry_once(player, "error", "")

        self.assertEqual(player._play.call_args.kwargs["start_position"], 0.0)

    def test_second_error_is_not_refreshed_again(self):
        player = make_player(attempted=True, state=State.Stopped)

        retry_once(player, "error", "")

        player.track.refresh_stream.assert_not_called()
        player._play.assert_not_called()

    def test_normal_end_does_not_refresh(self):
        player = make_player(state=State.Stopped)

        player.on_end_file("eof")

        player.track.refresh_stream.assert_not_called()
        player._play.assert_not_called()
