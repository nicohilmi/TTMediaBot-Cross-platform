"""FFmpeg based audio engine.

FFmpeg decodes any local file or network stream to raw PCM (48 kHz, stereo,
signed 16 bit) on its standard output. A small pipeline of threads then hands
that PCM, paced in real time, to an *audio sink*. In TTMediaBot the sink is the
TeamTalk virtual sound device, so no sound card, PulseAudio or virtual audio
cable is needed and the very same code runs on Windows and Linux.

    ffmpeg --stdout--> reader thread --queue--> pump thread --> sink
                          (stderr thread parses duration / metadata / errors)

The engine replaces what libmpv used to do for the bot: play, pause, stop,
seek, volume, playback speed and end-of-file notifications.
"""

from __future__ import annotations

import array
import logging
import queue
import re
import subprocess
import sys
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional, Set

from bot.ffmpeg_locator import hidden_process_kwargs

try:  # numpy is optional: it only makes volume scaling cheaper.
    import numpy as _np
except Exception:  # pragma: no cover - depends on the environment
    _np = None

SAMPLE_RATE = 48000
CHANNELS = 2
SAMPLE_WIDTH = 2  # bytes, signed 16 bit
FRAME_MS = 20
FRAME_SECONDS = FRAME_MS / 1000.0
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
FRAME_BYTES = FRAME_SAMPLES * CHANNELS * SAMPLE_WIDTH

# How far ahead of real time frames are handed to the sink. A small lead hides
# scheduler jitter (Windows timers are coarse) while keeping volume changes and
# pause responsive.
SINK_LEAD_SECONDS = 0.12
# Frames that must be buffered before playback of a (re)started stream begins.
PREBUFFER_FRAMES = 10
# Silence (stalled network) longer than this releases the sink.
UNDERRUN_RELEASE_SECONDS = 1.0

END_EOF = "eof"
END_ERROR = "error"

_DURATION_RE = re.compile(r"^\s*Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_METADATA_RE = re.compile(r"^\s{4}(\S.*?)\s*:\s?(.*)$")

_HTTP_OPTIONS_CACHE: Dict[str, Set[str]] = {}
_HTTP_OPTIONS_LOCK = threading.Lock()


def volume_to_gain(volume: float, curve: str = "cubic") -> float:
    """Map the bot volume (0-100) to a linear amplitude factor.

    libmpv scaled its volume cubically, so the default ``cubic`` curve keeps the
    loudness of every existing volume setting (50 stays 50). Use ``linear`` for
    a straight percentage.
    """
    fraction = max(float(volume), 0.0) / 100.0
    return fraction ** 3 if curve == "cubic" else fraction


def tempo_filters(speed: float) -> List[str]:
    """atempo filters for a playback speed. Each factor stays in 0.5-2.0 so old
    FFmpeg versions (which cap atempo at 2.0) work too."""
    if abs(speed - 1.0) < 0.001:
        return []
    filters: List[str] = []
    remaining = speed
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append("atempo={:.4f}".format(remaining))
    return filters


def apply_gain(frame: bytes, previous: float, target: float) -> bytes:
    """Scale a block of s16le PCM, ramping linearly from ``previous`` to
    ``target`` so volume steps (fades) do not click."""
    usable = len(frame) - (len(frame) % (CHANNELS * SAMPLE_WIDTH))
    if usable != len(frame):
        frame = frame[:usable]
    if not frame or (previous == 1.0 and target == 1.0):
        return frame
    if _np is not None:
        samples = _np.frombuffer(frame, dtype="<i2").astype(_np.float32)
        if previous == target:
            samples *= target
        else:
            frames = samples.shape[0] // CHANNELS
            ramp = _np.linspace(previous, target, frames, endpoint=False, dtype=_np.float32)
            samples = (samples.reshape(frames, CHANNELS) * ramp[:, None]).reshape(-1)
        _np.clip(samples, -32768, 32767, out=samples)
        return samples.astype("<i2").tobytes()
    pcm = array.array("h")
    pcm.frombytes(frame)
    if sys.byteorder == "big":
        pcm.byteswap()
    scaled = array.array(
        "h", [max(-32768, min(32767, int(sample * target))) for sample in pcm]
    )
    if sys.byteorder == "big":
        scaled.byteswap()
    return scaled.tobytes()


def _supported_http_options(ffmpeg_path: str) -> Set[str]:
    """Names of the HTTP protocol options this ffmpeg build understands.

    Passing an option an older ffmpeg does not know makes it exit with an
    error, so optional flags are only added when they are listed.
    """
    with _HTTP_OPTIONS_LOCK:
        cached = _HTTP_OPTIONS_CACHE.get(ffmpeg_path)
        if cached is not None:
            return cached
    names: Set[str] = set()
    try:
        result = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-h", "protocol=http"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=15,
            **hidden_process_kwargs(),
        )
        text = result.stdout.decode("utf-8", errors="replace")
        names = set(re.findall(r"^\s+-([a-z_]+)\s", text, flags=re.MULTILINE))
    except (OSError, subprocess.SubprocessError) as error:
        logging.warning(f"[FFmpeg] Could not query HTTP options: {error}")
    with _HTTP_OPTIONS_LOCK:
        _HTTP_OPTIONS_CACHE[ffmpeg_path] = names
    return names


class AudioSink:
    """Where decoded PCM goes. Implemented by the TeamTalk wrapper."""

    def write(self, pcm: bytes, sample_rate: int, channels: int) -> bool:
        raise NotImplementedError

    def end(self) -> None:
        raise NotImplementedError


class _Request:
    __slots__ = ("url", "headers", "user_agent")

    def __init__(
        self, url: str, headers: Optional[Dict[str, str]], user_agent: Optional[str]
    ) -> None:
        self.url = url
        self.headers = dict(headers or {})
        self.user_agent = user_agent


class _Session:
    """One running ffmpeg process and its threads."""

    def __init__(self, session_id: int, start: float, speed: float, buffer_frames: int):
        self.id = session_id
        self.start_offset = start
        self.speed = speed
        self.proc: Optional[subprocess.Popen] = None
        self.buffer: "queue.Queue[Optional[bytes]]" = queue.Queue(maxsize=buffer_frames)
        self.cancelled = threading.Event()
        self.sent_frames = 0
        self.returncode: Optional[int] = None
        self.duration: Optional[float] = None
        self.metadata: Dict[str, str] = {}
        self.stderr_tail: Deque[str] = deque(maxlen=40)
        self.audio_started = False
        self.threads: List[threading.Thread] = []
        self.pump_thread: Optional[threading.Thread] = None

    @property
    def position(self) -> float:
        return self.start_offset + self.sent_frames * FRAME_SECONDS * self.speed


class FFmpegEngine:
    def __init__(
        self,
        ffmpeg_path: str,
        sink: AudioSink,
        *,
        buffer_seconds: float = 5.0,
        network_timeout: float = 30.0,
        volume_curve: str = "cubic",
        on_end: Optional[Callable[[str, str], None]] = None,
        on_event: Optional[Callable[[str], None]] = None,
        on_metadata: Optional[Callable[[str, Any], None]] = None,
    ) -> None:
        self._ffmpeg = ffmpeg_path
        self._sink = sink
        self._buffer_frames = max(int(buffer_seconds * 1000 / FRAME_MS), PREBUFFER_FRAMES * 2)
        self._network_timeout = max(float(network_timeout), 1.0)
        self._volume_curve = volume_curve
        self._on_end = on_end
        self._on_event = on_event
        self._on_metadata = on_metadata

        self._op_lock = threading.RLock()  # serialises play/stop/seek
        self._lock = threading.Lock()  # guards _session
        self._session: Optional[_Session] = None
        self._session_counter = 0
        self._request: Optional[_Request] = None
        self._run_event = threading.Event()
        self._run_event.set()
        self._volume = 100.0
        self._speed = 1.0
        self._last_gain = volume_to_gain(self._volume, self._volume_curve)
        self._sink_lock = threading.Lock()
        self._sink_open = False
        self._sink_failing = False
        self._sink_last_warning = 0.0
        self._sink_exceptions = 0
        self._closed = False
        self._last_position = 0.0

    # ------------------------------------------------------------------ state

    @property
    def last_position(self) -> float:
        """Position (seconds) reached by the stream that ended most recently."""
        return self._last_position

    @property
    def volume(self) -> float:
        return self._volume

    @volume.setter
    def volume(self, value: float) -> None:
        self._volume = max(float(value), 0.0)

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def paused(self) -> bool:
        return not self._run_event.is_set()

    @property
    def idle(self) -> bool:
        """True when no stream is loaded (never started, stopped or finished)."""
        with self._lock:
            return self._session is None

    @property
    def position(self) -> float:
        with self._lock:
            session = self._session
        return session.position if session else 0.0

    @property
    def duration(self) -> Optional[float]:
        """Length in seconds, or None for live streams / not yet known."""
        with self._lock:
            session = self._session
        return session.duration if session else None

    @property
    def metadata(self) -> Dict[str, str]:
        with self._lock:
            session = self._session
        return dict(session.metadata) if session else {}

    @property
    def media_title(self) -> str:
        metadata = self.metadata
        for key in ("title", "TITLE", "StreamTitle", "icy-name", "name"):
            if metadata.get(key):
                return metadata[key]
        return ""

    # --------------------------------------------------------------- control

    def play(
        self,
        url: str,
        start: float = 0.0,
        headers: Optional[Dict[str, str]] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        """Start playing ``url`` (replacing whatever is playing). Never blocks
        on the network; failures are reported through ``on_end``."""
        with self._op_lock:
            if self._closed:
                return
            self._request = _Request(url, headers, user_agent)
            self._run_event.set()
            self._start_session(max(start, 0.0))

    def pause(self) -> None:
        self._run_event.clear()

    def resume(self) -> None:
        self._run_event.set()

    def stop(self) -> None:
        """Stop playback silently (no end notification)."""
        with self._op_lock:
            with self._lock:
                session, self._session = self._session, None
            self._request = None
            self._run_event.set()
            if session:
                self._kill(session)
            self._close_sink()

    def close(self) -> None:
        self._closed = True
        self.stop()

    def seek(self, delta: float, force: bool = False) -> bool:
        """Seek relative to the current position.

        Returns False when nothing is playing or the stream cannot be seeked.
        Streams with an unknown length (live radio) are only seeked with
        ``force=True``, for sources the caller knows to be seekable.
        """
        with self._op_lock:
            with self._lock:
                session = self._session
            if session is None or self._request is None:
                return False
            if session.duration is None and not force:
                return False
            return self._restart_at(session.position + delta, session.duration)

    def set_speed(self, speed: float, force: bool = False) -> None:
        """Change the playback speed. A running seekable stream restarts at its
        current position; otherwise the speed applies from the next start."""
        with self._op_lock:
            self._speed = speed
            with self._lock:
                session = self._session
            if session is None or self._request is None:
                return
            if session.duration is None and not force:
                return
            self._restart_at(session.position, session.duration)

    # -------------------------------------------------------------- internals

    def _restart_at(self, position: float, duration: Optional[float]) -> bool:
        position = max(position, 0.0)
        if duration is not None:
            position = min(position, duration)
        self._start_session(position)
        return True

    def _emit(self, name: str) -> None:
        if self._on_event:
            try:
                self._on_event(name)
            except Exception:
                logging.error("[FFmpeg] event callback failed", exc_info=True)

    def _build_command(self, request: _Request, start: float, speed: float) -> List[str]:
        cmd = [self._ffmpeg, "-hide_banner", "-nostdin", "-nostats", "-loglevel", "info"]
        lowered = request.url.lower()
        if lowered.startswith(("http://", "https://")):
            supported = _supported_http_options(self._ffmpeg)
            if request.user_agent and "user_agent" in supported:
                cmd += ["-user_agent", request.user_agent]
            if request.headers and "headers" in supported:
                header_text = "".join(
                    "{}: {}\r\n".format(
                        str(key).replace("\r", "").replace("\n", ""),
                        str(value).replace("\r", "").replace("\n", ""),
                    )
                    for key, value in request.headers.items()
                    if str(key).lower() != "user-agent"
                )
                if header_text:
                    cmd += ["-headers", header_text]
            for flag, value in (
                ("reconnect", "1"),
                ("reconnect_streamed", "1"),
                ("reconnect_on_network_error", "1"),
                ("reconnect_delay_max", "5"),
            ):
                if flag in supported:
                    cmd += ["-" + flag, value]
            cmd += ["-rw_timeout", str(int(self._network_timeout * 1_000_000))]
        if start > 0.05:
            cmd += ["-ss", "{:.3f}".format(start)]
        cmd += ["-i", request.url, "-vn", "-sn", "-dn"]
        filters = tempo_filters(speed)
        if filters:
            cmd += ["-af", ",".join(filters)]
        cmd += [
            "-ac", str(CHANNELS),
            "-ar", str(SAMPLE_RATE),
            "-f", "s16le",
            "pipe:1",
        ]
        return cmd

    def _start_session(self, start: float) -> None:
        request = self._request
        if request is None:
            return
        with self._lock:
            old, self._session = self._session, None
        if old:
            self._kill(old)
        self._session_counter += 1
        session = _Session(self._session_counter, start, self._speed, self._buffer_frames)
        cmd = self._build_command(request, start, self._speed)
        logging.debug("[FFmpeg] Starting: %s", self._printable(cmd))
        try:
            session.proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=FRAME_BYTES * 8,
                **hidden_process_kwargs(),
            )
        except OSError as error:
            logging.error(f"[FFmpeg] Could not start '{self._ffmpeg}': {error}")
            self._notify_end_async(END_ERROR, str(error))
            return
        self._last_gain = volume_to_gain(self._volume, self._volume_curve)
        with self._lock:
            self._session = session
        self._emit("start-file")
        for name, target in (
            ("FFmpegStderr", self._read_stderr),
            ("FFmpegReader", self._read_stdout),
            ("FFmpegPump", self._pump),
        ):
            thread = threading.Thread(target=target, args=(session,), name=name, daemon=True)
            session.threads.append(thread)
            if name == "FFmpegPump":
                session.pump_thread = thread
            thread.start()

    @staticmethod
    def _printable(cmd: List[str]) -> str:
        safe: List[str] = []
        skip_next = False
        for part in cmd:
            if skip_next:
                safe.append("<hidden>")
                skip_next = False
                continue
            safe.append(part)
            if part == "-headers":
                skip_next = True
        return " ".join(safe)

    def _kill(self, session: _Session) -> None:
        session.cancelled.set()
        proc = session.proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2.0)
            except OSError:
                pass
        current = threading.current_thread()
        for thread in session.threads:
            if thread is not current:
                thread.join(timeout=1.0)
        for stream in (getattr(proc, "stdout", None), getattr(proc, "stderr", None)):
            try:
                if stream:
                    stream.close()
            except Exception:
                pass

    def _notify_end_async(self, reason: str, error: str) -> None:
        if not self._on_end:
            return

        def run() -> None:
            try:
                self._on_end(reason, error)
            except Exception:
                logging.error("[FFmpeg] end callback failed", exc_info=True)

        threading.Thread(target=run, name="FFmpegEnd", daemon=True).start()

    # ---------------------------------------------------------------- threads

    def _read_stderr(self, session: _Session) -> None:
        proc = session.proc
        in_input = False
        in_metadata = False
        metadata_done = False
        audio_seen = False
        try:
            for raw in iter(proc.stderr.readline, b""):
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line.strip():
                    continue
                session.stderr_tail.append(line)
                if line.startswith("Input #0"):
                    in_input, in_metadata = True, False
                    continue
                if line.startswith(("Output #0", "Stream mapping")):
                    in_input = in_metadata = False
                    continue
                if not in_input:
                    continue
                if line.strip() == "Metadata:" and line.startswith("  ") and not line.startswith("   "):
                    in_metadata = True
                    continue
                duration_match = _DURATION_RE.match(line)
                if duration_match:
                    in_metadata = False
                    hours, minutes, seconds = duration_match.groups()
                    session.duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
                    continue
                if "Duration: N/A" in line:
                    in_metadata = False
                    session.duration = None
                    continue
                if line.lstrip().startswith("Stream #"):
                    in_metadata = False
                    if not audio_seen and "Audio:" in line:
                        audio_seen = True
                        self._emit("audio-reconfig")
                        if not metadata_done:
                            metadata_done = True
                            self._emit("file-loaded")
                            self._publish_metadata(session)
                    continue
                if in_metadata:
                    match = _METADATA_RE.match(line)
                    if match:
                        session.metadata[match.group(1).strip()] = match.group(2).strip()
        except (OSError, ValueError):
            pass

    def _publish_metadata(self, session: _Session) -> None:
        if not self._on_metadata or session.cancelled.is_set():
            return
        title = ""
        for key in ("title", "TITLE", "StreamTitle", "icy-name", "name"):
            if session.metadata.get(key):
                title = session.metadata[key]
                break
        try:
            self._on_metadata("metadata", dict(session.metadata))
            if title:
                self._on_metadata("media-title", title)
        except Exception:
            logging.error("[FFmpeg] metadata callback failed", exc_info=True)

    def _read_stdout(self, session: _Session) -> None:
        proc = session.proc
        try:
            while not session.cancelled.is_set():
                data = proc.stdout.read(FRAME_BYTES)
                if not data:
                    break
                if len(data) < FRAME_BYTES:
                    data = data.ljust(FRAME_BYTES, b"\x00")
                if not self._put(session, data):
                    return
        except (OSError, ValueError):
            pass
        if session.cancelled.is_set():
            return
        try:
            session.returncode = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            session.returncode = proc.wait()
        self._put(session, None)

    @staticmethod
    def _put(session: _Session, item: Optional[bytes]) -> bool:
        while not session.cancelled.is_set():
            try:
                session.buffer.put(item, timeout=0.2)
                return True
            except queue.Full:
                continue
        return False

    def _pump(self, session: _Session) -> None:
        # Wait for a small prebuffer so playback starts without crackling.
        while (
            session.buffer.qsize() < PREBUFFER_FRAMES
            and session.returncode is None
            and not session.cancelled.is_set()
        ):
            time.sleep(0.01)
        base: Optional[float] = None
        sent_since_base = 0
        last_data = time.monotonic()
        while not session.cancelled.is_set():
            if not self._run_event.is_set():
                self._close_sink()
                base = None
                while not self._run_event.wait(0.1):
                    if session.cancelled.is_set():
                        return
                last_data = time.monotonic()
                continue
            try:
                frame = session.buffer.get(timeout=0.1)
            except queue.Empty:
                base = None
                if time.monotonic() - last_data > UNDERRUN_RELEASE_SECONDS:
                    self._close_sink()
                continue
            if frame is None:
                break
            last_data = time.monotonic()
            now = time.monotonic()
            if base is None:
                base, sent_since_base = now, 0
            due = base + sent_since_base * FRAME_SECONDS - SINK_LEAD_SECONDS
            delay = due - now
            if delay > 0:
                if session.cancelled.wait(delay):
                    return
            elif delay < -0.5:
                base, sent_since_base = now, 0
            sent_since_base += 1
            target = volume_to_gain(self._volume, self._volume_curve)
            frame = apply_gain(frame, self._last_gain, target)
            self._last_gain = target
            if session.cancelled.is_set():
                return
            self._write(frame)
            session.sent_frames += 1
            if not session.audio_started:
                session.audio_started = True
                self._emit("playback-restart")
        self._finish(session)

    def _finish(self, session: _Session) -> None:
        if session.cancelled.is_set():
            return
        with self._lock:
            if self._session is not session:
                return
            self._last_position = session.position
            self._session = None
        self._close_sink()
        reason = END_EOF if session.returncode == 0 else END_ERROR
        error = ""
        if reason == END_ERROR:
            error = " | ".join(list(session.stderr_tail)[-4:])
            logging.warning(
                f"[FFmpeg] Playback ended with an error (exit code {session.returncode}): {error}"
            )
        if self._on_end:
            try:
                self._on_end(reason, error)
            except Exception:
                logging.error("[FFmpeg] end callback failed", exc_info=True)

    # ------------------------------------------------------------------- sink

    def _write(self, frame: bytes) -> None:
        with self._sink_lock:
            try:
                ok = self._sink.write(frame, SAMPLE_RATE, CHANNELS)
                if not ok and not self._sink_failing:
                    time.sleep(0.005)  # one quick retry, e.g. a momentarily full queue
                    ok = self._sink.write(frame, SAMPLE_RATE, CHANNELS)
            except Exception:
                self._sink_exceptions += 1
                if self._sink_exceptions == 1:
                    logging.error("[FFmpeg] audio sink failed (further errors are counted, not logged)", exc_info=True)
                ok = False
            if ok:
                self._sink_open = True
                self._sink_failing = False
                return
            self._sink_failing = True
            now = time.monotonic()
            if now - self._sink_last_warning > 30:
                self._sink_last_warning = now
                logging.warning(
                    "[FFmpeg] The audio sink refused audio (not connected to a channel "
                    "or no permission to transmit voice?). Audio is being dropped."
                )

    def _close_sink(self) -> None:
        with self._sink_lock:
            if not self._sink_open:
                return
            self._sink_open = False
            try:
                self._sink.end()
            except Exception:
                logging.error("[FFmpeg] closing the audio sink failed", exc_info=True)
