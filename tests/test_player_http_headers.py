from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from bot.player import Player


class PlayerHttpHeaderTests(TestCase):
    def _make_player(self):
        player = object.__new__(Player)
        player.track = SimpleNamespace(
            extra_info={"http_headers": {"User-Agent": "custom-agent", "Referer": "https://example.test/page"}}
        )
        player.track_list = []
        player.track_index = -1
        player.cache = SimpleNamespace(recents=[])
        player.cache_manager = SimpleNamespace(save=Mock())
        player._engine = Mock()
        player._default_user_agent = "default-agent"
        player._start_playback_trace = Mock(return_value=1)
        player._log_playback_timing = Mock()
        player._schedule_prefetch = Mock()
        return player

    def test_passes_track_http_headers_to_ffmpeg(self):
        player = self._make_player()

        player._play("https://cdn.example.test/audio.mp3", save_to_recents=False)

        player._engine.play.assert_called_once_with(
            "https://cdn.example.test/audio.mp3",
            start=0.0,
            headers={"Referer": "https://example.test/page"},
            user_agent="custom-agent",
        )

    def test_plain_url_uses_default_user_agent_and_no_headers(self):
        player = self._make_player()
        player.track.extra_info = None

        player._play("https://radio.example.test/live", save_to_recents=False)

        player._engine.play.assert_called_once_with(
            "https://radio.example.test/live",
            start=0.0,
            headers={},
            user_agent="default-agent",
        )

    def test_start_position_is_forwarded(self):
        player = self._make_player()

        player._play("https://cdn.example.test/a.m4a", save_to_recents=False, start_position=12.5)

        self.assertEqual(player._engine.play.call_args.kwargs["start"], 12.5)
