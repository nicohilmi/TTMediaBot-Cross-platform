"""A broadcast whose playlist is served while its segments are refused used to play silence forever.

FFmpeg does not fail in that case: it stays alive, prints "HTTP error 403 Forbidden" every few
seconds and delivers no audio, so the end callback (which makes the player ask for a fresh link)
was never called. The engine now gives such a stream up by itself.
"""
import http.server
import io
import threading
import time
from unittest import TestCase, skipUnless

from bot import ffmpeg_locator
from bot.player import ffmpeg_engine as fe

FFMPEG = ffmpeg_locator.find_ffmpeg()

PLAYLIST = "https://manifest.googlevideo.com/api/manifest/hls_playlist/expire/1900000000/itag/91/playlist/index.m3u8"


class SilentProcess:
    """An ffmpeg that is alive, prints some stderr and never delivers audio."""

    def __init__(self, stderr_text=""):
        self.stderr = io.BytesIO(stderr_text.encode())
        self.stdout = None
        self.terminated = False

    def poll(self):
        return 0 if self.terminated else None

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0


class RecordingSink(fe.AudioSink):
    def write(self, pcm, sample_rate, channels):
        return True

    def end(self):
        pass


class Recorder:
    def __init__(self):
        self.ended = []
        self.event = threading.Event()

    def __call__(self, reason, error):
        self.ended.append((reason, error))
        self.event.set()


def make_engine():
    recorder = Recorder()
    engine = fe.FFmpegEngine("ffmpeg", RecordingSink(), on_end=recorder)
    return engine, recorder


def make_session(engine, playlist=True, stderr_text=""):
    session = fe._Session(1, 0.0, 1.0, 400, playlist=playlist)
    session.proc = SilentProcess(stderr_text)
    engine._session = session
    return session


class PlaylistUrlTests(TestCase):
    def test_hls_links_are_recognised(self):
        self.assertTrue(fe.is_playlist_url(PLAYLIST))
        self.assertTrue(fe.is_playlist_url("https://x.test/live/index.m3u8?token=1"))
        self.assertTrue(fe.is_playlist_url("https://manifest.googlevideo.com/api/manifest/hls_variant/pot/AbC/file/index"))

    def test_ordinary_streams_are_not_playlists(self):
        self.assertFalse(fe.is_playlist_url("https://rr1.googlevideo.com/videoplayback?expire=1&itag=251"))
        self.assertFalse(fe.is_playlist_url("song.mp3"))
        self.assertFalse(fe.is_playlist_url(""))


class DenialCountingTests(TestCase):
    DENIED = "[https @ 000001f460b758c0] HTTP error 403 Forbidden\r\n"

    def test_repeated_refusals_before_any_audio_end_a_playlist_stream(self):
        engine, _ = make_engine()
        session = make_session(engine, stderr_text=self.DENIED * 3)
        with self.assertLogs(level="WARNING"):
            engine._read_stderr(session)
        self.assertEqual(session.http_denials, 3)
        reason = fe.FFmpegEngine._stalled_start_reason(session, 0.0)
        self.assertIn("refused the stream 3 times", reason)

    def test_fewer_refusals_are_only_noticed(self):
        engine, _ = make_engine()
        session = make_session(engine, stderr_text=self.DENIED * 2)
        with self.assertLogs(level="WARNING"):
            engine._read_stderr(session)
        self.assertEqual(fe.FFmpegEngine._stalled_start_reason(session, 0.0), "")

    def test_refusals_after_audio_started_are_left_alone(self):
        # a broadcast that played and then gets one refused segment is the player's business
        engine, _ = make_engine()
        text = (
            "Input #0, hls, from 'x':\r\n"
            "  Stream #0:0: Audio: aac, 48000 Hz, stereo\r\n"
            + self.DENIED * 5
        )
        session = make_session(engine, stderr_text=text)
        with self.assertLogs(level="WARNING"):
            engine._read_stderr(session)
        self.assertEqual(session.http_denials, 0)
        self.assertEqual(fe.FFmpegEngine._stalled_start_reason(session, 1.0), "")

    def test_an_ordinary_stream_is_never_judged_by_this_rule(self):
        engine, _ = make_engine()
        session = make_session(engine, playlist=False, stderr_text=self.DENIED * 6)
        with self.assertLogs(level="WARNING"):
            engine._read_stderr(session)
        self.assertEqual(session.http_denials, 0)
        self.assertEqual(
            fe.FFmpegEngine._stalled_start_reason(session, fe.PLAYLIST_START_TIMEOUT_SECONDS + 100), ""
        )


class StartTimeoutTests(TestCase):
    def test_a_playlist_without_audio_is_given_up_after_the_timeout(self):
        engine, _ = make_engine()
        session = make_session(engine)
        self.assertEqual(fe.FFmpegEngine._stalled_start_reason(session, 5.0), "")
        late = fe.FFmpegEngine._stalled_start_reason(session, fe.PLAYLIST_START_TIMEOUT_SECONDS + 1)
        self.assertIn("no audio", late)


class AbortTests(TestCase):
    def test_a_silent_stream_is_reported_as_a_failed_stream_once(self):
        engine, recorder = make_engine()
        session = make_session(engine, stderr_text="")
        session.stderr_tail.extend(["[https @ 1] HTTP error 403 Forbidden"])
        with self.assertLogs(level="WARNING") as logs:
            engine._abort_stalled(session, "the server refused the stream 3 times before any audio")
            engine._abort_stalled(session, "second call must do nothing")
        self.assertTrue(recorder.event.wait(2.0))
        time.sleep(0.1)
        self.assertEqual(len(recorder.ended), 1)
        reason, error = recorder.ended[0]
        self.assertEqual(reason, fe.END_ERROR)
        self.assertIn("refused the stream", error)
        self.assertIn("403", error)
        self.assertTrue(engine.idle)
        self.assertTrue(session.proc.terminated)
        self.assertEqual(sum("Giving up on a stream" in line for line in logs.output), 1)

    def test_a_stream_stopped_by_the_user_meanwhile_is_not_reported(self):
        engine, recorder = make_engine()
        session = make_session(engine)
        engine._session = None  # stop() took the session
        engine._abort_stalled(session, "late watchdog")
        time.sleep(0.2)
        self.assertEqual(recorder.ended, [])

    def test_the_pump_ends_a_silent_playlist_stream_with_an_error(self):
        engine, recorder = make_engine()
        session = make_session(engine)
        session.abort_reason = "the server refused the stream 3 times before any audio"
        thread = threading.Thread(target=engine._pump, args=(session,), daemon=True)
        with self.assertLogs(level="WARNING"):
            thread.start()
            self.assertTrue(recorder.event.wait(3.0))
        thread.join(2.0)
        self.assertEqual(recorder.ended[0][0], fe.END_ERROR)

    def test_a_healthy_playlist_stream_is_left_alone(self):
        engine, recorder = make_engine()
        session = make_session(engine)
        silence = bytes(fe.FRAME_BYTES)
        for _ in range(fe.PREBUFFER_FRAMES + 2):
            session.buffer.put(silence)
        session.buffer.put(None)
        session.returncode = 0
        thread = threading.Thread(target=engine._pump, args=(session,), daemon=True)
        thread.start()
        self.assertTrue(recorder.event.wait(5.0))
        thread.join(2.0)
        self.assertEqual(recorder.ended[0][0], fe.END_EOF)
        self.assertEqual(session.abort_reason, "")


class _RefusingSegmentsHandler(http.server.BaseHTTPRequestHandler):
    """Like the YouTube manifest server without a PO token: the playlist is fine, segments get 403."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.endswith(".m3u8"):
            body = b"#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:5\n#EXT-X-MEDIA-SEQUENCE:0\n"
            for number in range(3):
                body += b"#EXTINF:5.0,\n/seg/%d.ts\n" % number
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
        else:
            body = b"forbidden"
            self.send_response(403)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@skipUnless(FFMPEG, "ffmpeg is not available")
class RefusedBroadcastEndToEndTests(TestCase):
    def test_a_broadcast_whose_segments_are_refused_ends_with_an_error_instead_of_playing_silence(self):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _RefusingSegmentsHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        recorder = Recorder()
        engine = fe.FFmpegEngine(FFMPEG, RecordingSink(), on_end=recorder)
        try:
            url = "http://127.0.0.1:%d/hls_playlist/index.m3u8" % server.server_address[1]
            with self.assertLogs(level="WARNING"):
                engine.play(url)
                # Normally within a second; the start timeout is the safety net.
                self.assertTrue(recorder.event.wait(fe.PLAYLIST_START_TIMEOUT_SECONDS + 15))
            self.assertEqual(recorder.ended[0][0], fe.END_ERROR)
            self.assertTrue(engine.idle)
        finally:
            engine.close()
            server.shutdown()
            server.server_close()
