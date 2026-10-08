from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from bot import errors
from bot.modules.stream_resolvers import (
    DEFAULT_USER_AGENT,
    GetemStreamResolver,
    StreamResolution,
    StreamResolverRegistry,
)
from bot.modules.streamer import Streamer
from bot.player.enums import TrackType


GETEM_URL = (
    "https://getem.boun.edu.tr/getemPlayerYeni/getemplayer.php?"
    "folder=SesliBetimlemeTurkce/MandalinaBahcesi&"
    "file=001-MandalinaBahcesi.mp3"
)


class FakeResponse:
    def __init__(self, text: str, url: str = GETEM_URL, status_code: int = 200) -> None:
        self.text = text
        self.url = url
        self.status_code = status_code
        self.closed = False
        self.headers = {"Content-Type": "text/html; charset=utf-8"}
        self.encoding = "utf-8"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise errors.ServiceError(str(self.status_code))

    def iter_content(self, chunk_size: int = 65536):
        yield self.text.encode(self.encoding)

    def close(self) -> None:
        self.closed = True


class GetemStreamResolverTests(TestCase):
    def test_supports_getem_player_url_only(self):
        resolver = GetemStreamResolver(session=Mock())

        self.assertTrue(resolver.supports(GETEM_URL))
        self.assertFalse(resolver.supports("https://getem.boun.edu.tr/"))
        self.assertFalse(resolver.supports("https://example.com/getemPlayerYeni/getemplayer.php"))

    def test_extracts_audio_source_and_sets_playback_headers(self):
        response = FakeResponse(
            '<audio><source src="/media/Mandalina/001-MandalinaBahcesi.mp3"></audio>'
        )
        session = Mock()
        session.get.return_value = response
        resolver = GetemStreamResolver(session=session)

        resolution = resolver.resolve(GETEM_URL)

        self.assertEqual(
            resolution.url,
            "https://getem.boun.edu.tr/media/Mandalina/001-MandalinaBahcesi.mp3",
        )
        self.assertEqual(resolution.name, "001-MandalinaBahcesi.mp3")
        self.assertEqual(resolution.format, "mp3")
        self.assertEqual(resolution.http_headers["User-Agent"], DEFAULT_USER_AGENT)
        self.assertEqual(resolution.http_headers["Referer"], GETEM_URL)
        self.assertTrue(response.closed)

    def test_extracts_javascript_mp3_candidate(self):
        response = FakeResponse(
            "<script>player.setMedia({mp3: '../audio/001-MandalinaBahcesi.mp3'});</script>"
        )
        session = Mock()
        session.get.return_value = response
        resolver = GetemStreamResolver(session=session)

        resolution = resolver.resolve(GETEM_URL)

        self.assertEqual(
            resolution.url,
            "https://getem.boun.edu.tr/audio/001-MandalinaBahcesi.mp3",
        )

    def test_ignores_unrelated_script_src_values(self):
        response = FakeResponse(
            "<script>src = '/images/player.png'; mp3 = '/audio/track.mp3';</script>"
        )
        session = Mock()
        session.get.return_value = response
        resolver = GetemStreamResolver(session=session)

        resolution = resolver.resolve(GETEM_URL)

        self.assertEqual(resolution.url, "https://getem.boun.edu.tr/audio/track.mp3")

    def test_rejects_getem_page_without_media(self):
        response = FakeResponse("<html><body>No player source</body></html>")
        session = Mock()
        session.get.return_value = response
        resolver = GetemStreamResolver(session=session)

        with self.assertRaises(errors.ServiceError):
            resolver.resolve(GETEM_URL)

        self.assertTrue(response.closed)


class StreamerResolverTests(TestCase):
    def test_generic_resolver_runs_before_direct_fallback(self):
        bot = SimpleNamespace(
            config=SimpleNamespace(),
            service_manager=SimpleNamespace(services={}),
        )
        streamer = Streamer(bot)
        streamer.stream_resolvers = Mock(spec=StreamResolverRegistry)
        streamer.stream_resolvers.resolve.return_value = StreamResolution(
            url="https://cdn.example.test/audio.mp3",
            name="audio.mp3",
            format="mp3",
            http_headers={"Referer": GETEM_URL},
        )

        tracks = streamer.get(GETEM_URL, is_admin=False)

        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].url, "https://cdn.example.test/audio.mp3")
        self.assertEqual(tracks[0].type, TrackType.Direct)
        self.assertEqual(tracks[0].extra_info["http_headers"]["Referer"], GETEM_URL)

    def test_unknown_url_stays_direct_when_no_resolver_matches(self):
        bot = SimpleNamespace(
            config=SimpleNamespace(),
            service_manager=SimpleNamespace(services={}),
        )
        streamer = Streamer(bot)
        streamer.stream_resolvers = Mock(spec=StreamResolverRegistry)
        streamer.stream_resolvers.resolve.return_value = None

        tracks = streamer.get("https://radio.example.test/live", is_admin=False)

        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].url, "https://radio.example.test/live")
        self.assertEqual(tracks[0].type, TrackType.Direct)
