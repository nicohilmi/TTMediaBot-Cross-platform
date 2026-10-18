"""Stutter used to leave no trace in the log."""
import queue
import threading
import time
from unittest import TestCase

from bot.player import ffmpeg_engine as fe


class RecordingSink(fe.AudioSink):
    def __init__(self):
        self.frames = 0

    def write(self, pcm, sample_rate, channels):
        self.frames += 1
        return True


class StallLoggingTests(TestCase):
    def _session(self):
        return fe._Session(1, 0.0, 1.0, 400)

    def test_underrun_is_logged_with_duration_and_position(self):
        session = self._session()
        with self.assertLogs(level="WARNING") as logs:
            fe.FFmpegEngine._note_underrun(session, 1.5)
        self.assertEqual(session.underruns, 1)
        self.assertAlmostEqual(session.underrun_seconds, 1.5)
        self.assertIn("underrun #1", logs.output[0])
        self.assertIn("1.50 s", logs.output[0])

    def test_underrun_logging_is_rate_limited(self):
        session = self._session()
        with self.assertLogs(level="WARNING") as logs:
            for _ in range(25):
                fe.FFmpegEngine._note_underrun(session, 0.2)
        self.assertEqual(session.underruns, 25)
        # Underruns 1 to 10 are logged one by one, after that only every 10th (#20).
        self.assertEqual(len(logs.output), 11)

    def test_late_frames_are_counted_and_logged_at_most_every_few_seconds(self):
        session = self._session()
        with self.assertLogs(level="WARNING") as logs:
            for lateness in (0.1, 0.3, 0.2):
                fe.FFmpegEngine._note_late_frame(session, lateness)
        self.assertEqual(session.late_frames, 3)
        self.assertAlmostEqual(session.max_late, 0.3)
        self.assertEqual(len(logs.output), 1)

    def test_network_notices_from_ffmpeg_stderr_are_recognised(self):
        for line in (
            "[https @ 0x55d] Will reconnect at 1048576 in 0 second(s), error=Connection reset by peer.",
            "[tcp @ 0x55d] Connection timed out",
            "[https @ 0x55d] HTTP error 403 Forbidden",
            "Error in the pull function.",
        ):
            self.assertIsNotNone(fe._NETWORK_NOTICE_RE.search(line), line)
        for line in ("Stream #0:0: Audio: opus, 48000 Hz", "  Duration: 00:03:14.30"):
            self.assertIsNone(fe._NETWORK_NOTICE_RE.search(line), line)

    def test_rebuffer_returns_at_once_when_enough_frames_are_queued(self):
        session = self._session()
        for _ in range(fe.PREBUFFER_FRAMES):
            session.buffer.put(b"x")
        started = time.monotonic()
        fe.FFmpegEngine._rebuffer(session)
        self.assertLess(time.monotonic() - started, 0.5)

    def test_rebuffer_gives_up_when_the_stream_has_ended(self):
        session = self._session()
        session.returncode = 0
        started = time.monotonic()
        fe.FFmpegEngine._rebuffer(session)
        self.assertLess(time.monotonic() - started, 0.5)

    def test_pump_survives_a_stall_counts_it_and_rebuffers(self):
        sink = RecordingSink()
        ends = []
        engine = fe.FFmpegEngine("ffmpeg", sink, on_end=lambda reason, error: ends.append(reason))
        session = self._session()
        engine._session = session
        frame = b"\x00" * fe.FRAME_BYTES
        for _ in range(fe.PREBUFFER_FRAMES + 2):
            session.buffer.put(frame)

        def producer():
            time.sleep(0.5)  # the "network" stalls: nothing arrives
            for _ in range(fe.PREBUFFER_FRAMES + 5):
                session.buffer.put(frame)
            session.returncode = 0
            session.buffer.put(None)

        threading.Thread(target=producer, daemon=True).start()
        with self.assertLogs(level="WARNING") as logs:
            engine._pump(session)
        self.assertGreaterEqual(session.underruns, 1)
        self.assertEqual(sink.frames, (fe.PREBUFFER_FRAMES + 2) + (fe.PREBUFFER_FRAMES + 5))
        self.assertTrue(any("underrun" in line for line in logs.output))
        self.assertEqual(ends, [fe.END_EOF])
