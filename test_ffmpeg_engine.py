import os
import shutil
import subprocess
import tempfile
import threading
import time
from unittest import TestCase, skipUnless

from bot import ffmpeg_locator
from bot.player import ffmpeg_engine as fe

FFMPEG = ffmpeg_locator.find_ffmpeg()


class RecordingSink(fe.AudioSink):
    def __init__(self):
        self.frames = []
        self.ended = 0

    def write(self, pcm, sample_rate, channels):
        self.frames.append(pcm)
        return True

    def end(self):
        self.ended += 1

    def peak(self):
        samples = b"".join(self.frames)
        values = memoryview(samples).cast("h")
        return max((abs(v) for v in values), default=0)


class PureFunctionTests(TestCase):
    def test_cubic_volume_matches_the_old_mpv_curve(self):
        self.assertAlmostEqual(fe.volume_to_gain(100), 1.0)
        self.assertAlmostEqual(fe.volume_to_gain(50), 0.125)
        self.assertEqual(fe.volume_to_gain(0), 0.0)
        self.assertAlmostEqual(fe.volume_to_gain(50, "linear"), 0.5)

    def test_tempo_filters_stay_inside_the_range_old_ffmpeg_accepts(self):
        self.assertEqual(fe.tempo_filters(1.0), [])
        self.assertEqual(fe.tempo_filters(1.5), ["atempo=1.5000"])
        self.assertEqual(len(fe.tempo_filters(4.0)), 2)
        self.assertEqual(len(fe.tempo_filters(0.25)), 2)

    def test_apply_gain_scales_and_clips(self):
        frame = (1000).to_bytes(2, "little", signed=True) * 4
        scaled = fe.apply_gain(frame, 0.5, 0.5)
        self.assertEqual(memoryview(scaled).cast("h")[0], 500)
        loud = (30000).to_bytes(2, "little", signed=True) * 4
        clipped = fe.apply_gain(loud, 2.0, 2.0)
        self.assertEqual(memoryview(clipped).cast("h")[0], 32767)

    def test_apply_gain_without_numpy_gives_the_same_result(self):
        frame = bytes(range(0, 200, 2)) * 2
        with_numpy = fe.apply_gain(frame, 0.25, 0.25)
        saved, fe._np = fe._np, None
        try:
            without_numpy = fe.apply_gain(frame, 0.25, 0.25)
        finally:
            fe._np = saved
        self.assertEqual(with_numpy, without_numpy)


class CommandTests(TestCase):
    def _engine(self):
        return fe.FFmpegEngine("ffmpeg", fe.AudioSink())

    def test_http_options_only_for_http_urls(self):
        engine = self._engine()
        fe._HTTP_OPTIONS_CACHE["ffmpeg"] = {"user_agent", "headers", "reconnect"}
        remote = engine._build_command(
            fe._Request("https://x.test/a.m4a", {"Referer": "https://r.test/"}, "agent"), 0.0, 1.0
        )
        self.assertIn("-user_agent", remote)
        self.assertIn("-headers", remote)
        self.assertIn("-reconnect", remote)
        local = engine._build_command(fe._Request("song.mp3", {"Referer": "x"}, "agent"), 0.0, 1.0)
        self.assertNotIn("-user_agent", local)
        self.assertNotIn("-headers", local)

    def test_seek_and_speed_are_in_the_command(self):
        command = self._engine()._build_command(fe._Request("song.mp3", None, None), 12.5, 2.0)
        self.assertEqual(command[command.index("-ss") + 1], "12.500")
        self.assertLess(command.index("-ss"), command.index("-i"))
        self.assertIn("atempo=2.0000", command[command.index("-af") + 1])
        self.assertEqual(command[-3:], ["-f", "s16le", "pipe:1"])

    def test_headers_cannot_inject_extra_lines(self):
        engine = self._engine()
        fe._HTTP_OPTIONS_CACHE["ffmpeg"] = {"headers"}
        command = engine._build_command(
            fe._Request("https://x.test/a", {"X-Test": "ok\r\nEvil: 1"}, None), 0.0, 1.0
        )
        self.assertEqual(command[command.index("-headers") + 1], "X-Test: okEvil: 1\r\n")


@skipUnless(FFMPEG, "ffmpeg is not available")
class PlaybackTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.mkdtemp()
        cls.tone = os.path.join(cls.directory, "tone.wav")
        subprocess.run(
            [FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
             "sine=frequency=440:duration=2", "-metadata", "title=Test Tone", cls.tone],
            check=True,
        )
        cls.long_tone = os.path.join(cls.directory, "long_tone.wav")
        subprocess.run(
            [FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
             "sine=frequency=440:duration=8", cls.long_tone],
            check=True,
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.directory, ignore_errors=True)

    def _play(self, **options):
        sink = RecordingSink()
        ends = []
        engine = fe.FFmpegEngine(
            FFMPEG, sink, on_end=lambda reason, error: ends.append((reason, error)), **options
        )
        return engine, sink, ends

    def _wait(self, ends, seconds=10):
        deadline = time.monotonic() + seconds
        while not ends and time.monotonic() < deadline:
            time.sleep(0.02)

    def test_plays_a_file_to_the_end(self):
        engine, sink, ends = self._play()
        engine.play(self.tone)
        self._wait(ends)
        self.assertEqual(ends[0][0], "eof")
        self.assertAlmostEqual(len(sink.frames) * fe.FRAME_SECONDS, 2.0, delta=0.1)
        self.assertTrue(engine.idle)
        self.assertGreaterEqual(sink.ended, 1)

    def test_volume_is_applied(self):
        loud, quiet = self._play(), self._play()
        loud[0].volume = 100
        quiet[0].volume = 50
        for engine, _, _ in (loud, quiet):
            engine.play(self.tone)
        self._wait(loud[2])
        self._wait(quiet[2])
        self.assertGreater(loud[1].peak(), 0)
        self.assertAlmostEqual(quiet[1].peak() / loud[1].peak(), 0.125, delta=0.02)

    def test_missing_file_reports_an_error(self):
        engine, _, ends = self._play()
        engine.play(os.path.join(self.directory, "missing.wav"))
        self._wait(ends)
        self.assertEqual(ends[0][0], "error")

    def test_stop_does_not_notify(self):
        engine, _, ends = self._play()
        engine.play(self.tone)
        time.sleep(0.4)
        engine.stop()
        time.sleep(0.3)
        self.assertEqual(ends, [])
        self.assertTrue(engine.idle)

    def test_seek_moves_the_position(self):
        engine, _, ends = self._play()
        engine.play(self.long_tone)
        time.sleep(0.6)
        self.assertTrue(engine.seek(3.0))
        time.sleep(0.5)
        self.assertGreater(engine.position, 3.3)
        engine.stop()

    def test_pause_stops_the_audio(self):
        engine, sink, ends = self._play()
        engine.play(self.tone)
        time.sleep(0.5)
        engine.pause()
        time.sleep(0.3)
        count = len(sink.frames)
        time.sleep(0.5)
        self.assertEqual(len(sink.frames), count)
        engine.resume()
        time.sleep(0.3)
        self.assertGreater(len(sink.frames), count)
        engine.stop()
