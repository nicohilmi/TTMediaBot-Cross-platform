import os
import shutil
import subprocess
import tempfile
import threading
import time
from unittest import TestCase, skipUnless

from bot import ffmpeg_locator
from bot.player import Player, ffmpeg_engine as fe
from bot.player.enums import State

FFMPEG = ffmpeg_locator.find_ffmpeg()


class RecordingSink(fe.AudioSink):
    def __init__(self):
        self.frames = []

    def write(self, pcm, sample_rate, channels):
        self.frames.append(pcm)
        return True

    def end(self):
        pass

    @staticmethod
    def peak_of(frame):
        values = memoryview(frame).cast("h")
        return max((abs(v) for v in values), default=0)


class FadeCurveTests(TestCase):
    def test_fade_starts_near_full_level_and_ends_silent(self):
        fade = fe._Fade(session_id=1, frames=100)
        factors = [fade.next_multiplier() for _ in range(100)]
        self.assertGreater(factors[0], 0.9)
        self.assertEqual(factors[-1], 0.0)
        self.assertEqual(fade.outcome, fe.FADE_DONE)
        self.assertTrue(fade.done.is_set())

    def test_fade_is_a_straight_line_in_db(self):
        fade = fe._Fade(session_id=1, frames=100)
        factors = [fade.next_multiplier() for _ in range(99)]
        # Halfway through, the level is half of the fade's dB range down.
        halfway = 20 * __import__("math").log10(factors[49])
        self.assertAlmostEqual(halfway, -fe.FADE_RANGE_DB / 2, delta=0.6)
        # Each equal step lowers the level by the same number of dB.
        steps = [
            20 * __import__("math").log10(factors[i + 1] / factors[i])
            for i in range(98)
        ]
        self.assertAlmostEqual(max(steps), min(steps), delta=0.01)

    def test_fade_stays_silent_after_it_finished(self):
        fade = fe._Fade(session_id=1, frames=3)
        for _ in range(3):
            fade.next_multiplier()
        self.assertEqual(fade.next_multiplier(), 0.0)

    def test_first_outcome_wins(self):
        fade = fe._Fade(session_id=1, frames=10)
        fade.finish(fe.FADE_SUPERSEDED)
        fade.finish(fe.FADE_DONE)
        self.assertEqual(fade.outcome, fe.FADE_SUPERSEDED)


@skipUnless(FFMPEG, "ffmpeg is not available")
class EngineFadeTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.mkdtemp()
        cls.long_tone = os.path.join(cls.directory, "long_tone.wav")
        subprocess.run(
            [FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
             "sine=frequency=440:duration=12", cls.long_tone],
            check=True,
        )
        cls.short_tone = os.path.join(cls.directory, "short_tone.wav")
        subprocess.run(
            [FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
             "sine=frequency=440:duration=2", cls.short_tone],
            check=True,
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.directory, ignore_errors=True)

    def _engine(self):
        sink = RecordingSink()
        ends = []
        engine = fe.FFmpegEngine(
            FFMPEG, sink, on_end=lambda reason, error: ends.append(reason)
        )
        engine.volume = 100
        return engine, sink, ends

    def _fade_in_thread(self, engine, seconds):
        result = {}

        def run():
            started = time.monotonic()
            result["outcome"] = engine.fade_out_and_stop(seconds)
            result["elapsed"] = time.monotonic() - started

        thread = threading.Thread(target=run)
        thread.start()
        return thread, result

    def test_fade_lowers_the_level_step_by_step_and_stops(self):
        engine, sink, ends = self._engine()
        engine.play(self.long_tone)
        time.sleep(0.6)
        before = len(sink.frames)
        thread, result = self._fade_in_thread(engine, 1.5)
        thread.join(10)
        self.assertEqual(result["outcome"], fe.FADE_DONE)
        self.assertTrue(engine.idle)
        self.assertEqual(ends, [])  # a fade-out stop is not a natural end
        # 1.5 s of audio, one 20 ms frame at a time (stopping the ffmpeg process
        # afterwards can add up to a second, which nobody hears).
        self.assertGreaterEqual(result["elapsed"], 1.4)
        faded = [sink.peak_of(frame) for frame in sink.frames[before:]]
        self.assertAlmostEqual(len(faded), 75, delta=4)
        self.assertGreater(faded[0], 2000)  # starts at the normal level
        self.assertLess(faded[-1], 50)  # ends silent
        quarter = faded[len(faded) // 4]
        three_quarters = faded[3 * len(faded) // 4]
        self.assertLess(three_quarters, quarter)
        self.assertLess(quarter, faded[0])
        # The fade is its own gain factor: the volume setting is untouched.
        self.assertEqual(engine.volume, 100)

    def test_new_playback_during_a_fade_wins(self):
        engine, sink, _ = self._engine()
        engine.play(self.long_tone)
        time.sleep(0.4)
        thread, result = self._fade_in_thread(engine, 3.0)
        time.sleep(0.5)
        engine.play(self.long_tone)
        thread.join(10)
        self.assertEqual(result["outcome"], fe.FADE_SUPERSEDED)
        self.assertFalse(engine.idle)
        time.sleep(0.6)
        self.assertGreater(sink.peak_of(sink.frames[-1]), 2000)  # full level again
        engine.stop()

    def test_stop_during_a_fade_ends_it_at_once(self):
        engine, _, _ = self._engine()
        engine.play(self.long_tone)
        time.sleep(0.4)
        thread, result = self._fade_in_thread(engine, 5.0)
        time.sleep(0.4)
        engine.stop()
        thread.join(5)
        self.assertEqual(result["outcome"], fe.FADE_STOPPED)
        self.assertLess(result["elapsed"], 2.0)

    def test_track_that_ends_during_a_fade_reports_it(self):
        engine, _, ends = self._engine()
        engine.play(self.short_tone)
        time.sleep(1.3)
        thread, result = self._fade_in_thread(engine, 5.0)
        thread.join(10)
        self.assertEqual(result["outcome"], fe.FADE_ENDED)

    def test_nothing_to_fade_when_idle_or_paused(self):
        engine, _, _ = self._engine()
        self.assertEqual(engine.fade_out_and_stop(1.0), fe.FADE_IDLE)
        engine.play(self.long_tone)
        time.sleep(0.4)
        engine.pause()
        self.assertEqual(engine.fade_out_and_stop(1.0), fe.FADE_IDLE)
        engine.stop()

    def test_next_track_after_a_fade_plays_at_full_level(self):
        engine, sink, _ = self._engine()
        engine.play(self.long_tone)
        time.sleep(0.4)
        engine.fade_out_and_stop(0.6)
        sink.frames.clear()
        engine.play(self.long_tone)
        time.sleep(0.8)
        self.assertGreater(max(sink.peak_of(f) for f in sink.frames[-10:]), 2000)
        engine.stop()


class FakeEngine:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def fade_out_and_stop(self, duration):
        self.calls.append(("fade", duration))
        return self.outcome

    def stop(self):
        self.calls.append(("stop",))


def make_player(engine, state=State.Playing):
    player = object.__new__(Player)
    player._engine = engine
    player.state = state
    player._fading_out = False
    player._cancel_prefetch = lambda: None
    player.track_list = ["a", "b"]
    player.track = "a"
    player.track_index = 0
    player.is_playlist = True
    return player


class PlayerStopTests(TestCase):
    def test_stop_without_fade_stops_at_once(self):
        engine = FakeEngine(fe.FADE_DONE)
        player = make_player(engine)
        player.stop()
        self.assertEqual(engine.calls, [("stop",)])
        self.assertEqual(player.state, State.Stopped)

    def test_stop_with_fade_fades_then_clears_the_player(self):
        engine = FakeEngine(fe.FADE_DONE)
        player = make_player(engine)
        player.stop(2.5)
        self.assertEqual(engine.calls[0], ("fade", 2.5))
        self.assertEqual(player.state, State.Stopped)
        self.assertEqual(player.track_list, [])
        self.assertFalse(player._fading_out)

    def test_playback_started_during_the_fade_cancels_the_stop(self):
        engine = FakeEngine(fe.FADE_SUPERSEDED)
        player = make_player(engine)
        player.stop(2.5)
        self.assertEqual(player.state, State.Playing)
        self.assertEqual(player.track_list, ["a", "b"])
        self.assertEqual(engine.calls, [("fade", 2.5)])
        self.assertFalse(player._fading_out)

    def test_second_stop_during_the_fade_cuts_it_short(self):
        engine = FakeEngine(fe.FADE_DONE)
        player = make_player(engine)
        player._fading_out = True
        player.stop(2.5)
        self.assertEqual(engine.calls, [("stop",)])
        self.assertEqual(player.state, State.Stopped)

    def test_paused_playback_is_not_faded(self):
        engine = FakeEngine(fe.FADE_DONE)
        player = make_player(engine, state=State.Paused)
        player.stop(2.5)
        self.assertEqual(engine.calls, [("stop",)])
        self.assertEqual(player.state, State.Stopped)

    def test_the_flag_is_cleared_even_if_the_fade_fails(self):
        class Broken(FakeEngine):
            def fade_out_and_stop(self, duration):
                raise RuntimeError("boom")

        player = make_player(Broken(fe.FADE_DONE))
        with self.assertRaises(RuntimeError):
            player.stop(2.0)
        self.assertFalse(player._fading_out)
