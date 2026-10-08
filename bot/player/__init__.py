from __future__ import annotations
import html
import logging
import time
import threading
from typing import Any, Dict, Callable, List, Optional, TYPE_CHECKING
import random

from bot import errors, ffmpeg_locator
from bot.player.enums import Mode, State, TrackType
from bot.player.ffmpeg_engine import AudioSink, END_ERROR, FFmpegEngine
from bot.player.track import Track
from bot.player.queue_manager import QueueManager


if TYPE_CHECKING:
    from bot import Bot


PREFETCH_DELAY_SECONDS = 0.05
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36"
)
# After a stream error, a refreshed stream resumes where playback stopped, but
# only when at least this many seconds had been played.
RESUME_AFTER_ERROR_MIN_SECONDS = 3.0


class TeamTalkAudioSink(AudioSink):
    """Hands decoded audio to the TeamTalk client (virtual sound device).

    The TeamTalk client is created after the player, so it is looked up lazily.
    """

    def __init__(self, bot: "Bot") -> None:
        self._bot = bot

    def write(self, pcm: bytes, sample_rate: int, channels: int) -> bool:
        return self._bot.ttclient.insert_audio(pcm, sample_rate, channels)

    def end(self) -> None:
        self._bot.ttclient.end_audio_input()


class Player:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.config = bot.config.player
        self.cache = bot.cache
        self.cache_manager = bot.cache_manager
        ffmpeg_path = ffmpeg_locator.get_ffmpeg(self.config.ffmpeg_path)
        self._default_user_agent = DEFAULT_USER_AGENT
        self._engine = FFmpegEngine(
            ffmpeg_path,
            TeamTalkAudioSink(bot),
            buffer_seconds=self.config.buffer_seconds,
            network_timeout=self.config.network_timeout,
            volume_curve=self.config.volume_curve,
            on_end=self.on_end_file,
            on_event=self._on_engine_event,
            on_metadata=self.on_metadata_update,
        )
        self._engine.volume = self.config.default_volume
        self._refresh_in_progress = False
        self.track_list: List[Track] = []
        self.track: Track = Track()
        self.track_index: int = -1
        self.state = State.Stopped
        self.mode = Mode.TrackList
        self.volume = self.config.default_volume
        self.is_playlist: bool = False
        self._navigation_lock = threading.RLock()
        self._playback_trace_lock = threading.Lock()
        self._playback_trace_counter = 0
        self._playback_trace: Dict[str, Any] = {}
        self._pending_playback_context: Dict[str, Any] = {}
        self._prefetch_lock = threading.Lock()
        self._prefetch_timer_lock = threading.Lock()
        self._prefetch_timer: Optional[threading.Timer] = None

        self.queue: QueueManager = QueueManager()

    def initialize(self) -> None:
        logging.debug("Initializing player")
        logging.debug("Player initialized")

    def run(self) -> None:
        logging.debug("Player is ready (FFmpeg engine)")

    def close(self) -> None:
        logging.debug("Closing player")
        self._cancel_prefetch()
        if self.state != State.Stopped:
            self.stop()
        self._engine.close()
        logging.debug("Player closed")

    def play(
        self,
        tracks: Optional[List[Track]] = None,
        start_track_index: Optional[int] = None,
        is_playlist: Optional[bool] = None,
        timing_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        if tracks != None:
            self.track_list = tracks
            if is_playlist is not None:
                self.is_playlist = is_playlist
            else:
                self.is_playlist = len(tracks) > 1
            if not start_track_index and self.mode == Mode.Random:
                self.shuffle(True)
                self.track_index = self._index_list[0]
                self.track = self.track_list[self.track_index]
            else:
                self.track_index = start_track_index if start_track_index else 0
                self.track = tracks[self.track_index]
            self._pending_playback_context = timing_context or {}
            self._play(self.track.url)
        else:
            self._engine.resume()
        self._engine.volume = self.volume
        self.state = State.Playing

    def pause(self) -> None:
        self.state = State.Paused
        self._engine.pause()

    def stop(self) -> None:
        self._cancel_prefetch()
        self.state = State.Stopped
        self._engine.stop()
        self.track_list = []
        self.track = Track()
        self.track_index = -1
        self.is_playlist = False

    def _play(
        self,
        arg: str,
        save_to_recents: bool = True,
        start_position: float = 0.0,
        is_refresh: bool = False,
    ) -> None:
        trace = self._start_playback_trace()
        self._refresh_in_progress = is_refresh
        if save_to_recents:
            try:
                if 0 <= self.track_index < len(self.track_list):
                    track_raw = self.track_list[self.track_index].get_raw()
                    if not self.cache.recents or self.cache.recents[-1] != track_raw:
                        self.cache.recents.append(track_raw)
                        self.cache_manager.save()
            except Exception as e:
                logging.debug(f"[Player] Failed to save recents: {e}")

        # Per-track HTTP headers (e.g. from the YouTube bridge); the User-Agent
        # is passed separately because FFmpeg has a dedicated option for it.
        extra_info = getattr(self.track, "extra_info", None) or {}
        headers = extra_info.get("http_headers", {}) or {}
        user_agent = headers.get("User-Agent") or self._default_user_agent
        other_headers = {
            key: value for key, value in headers.items() if key.lower() != "user-agent"
        }
        self._engine.play(
            arg,
            start=start_position,
            headers=other_headers,
            user_agent=user_agent,
        )
        self._log_playback_timing("ffmpeg_play_submitted", trace)
        self._schedule_prefetch()

    def _schedule_prefetch(self) -> None:
        with self._prefetch_timer_lock:
            if self._prefetch_timer is not None:
                self._prefetch_timer.cancel()
            timer = threading.Timer(
                PREFETCH_DELAY_SECONDS,
                self._prefetch_next_track,
            )
            timer.daemon = True
            self._prefetch_timer = timer
            timer.start()

    def _cancel_prefetch(self) -> None:
        with self._prefetch_timer_lock:
            if self._prefetch_timer is not None:
                self._prefetch_timer.cancel()
                self._prefetch_timer = None

    def _start_playback_trace(self) -> Dict[str, Any]:
        with self._playback_trace_lock:
            self._playback_trace_counter += 1
            timing_context = self._pending_playback_context
            self._pending_playback_context = {}
            trace = {
                "id": self._playback_trace_counter,
                "started_at": time.perf_counter(),
                "track": self.track.name or "Unknown",
                "service": self.track.service or "unknown",
                "timing_context": timing_context,
                "summary_logged": False,
            }
            self._playback_trace = trace
        self._log_playback_timing("player_play_started", trace)
        return trace

    def _log_playback_timing(
        self, stage: str, trace: Optional[Dict[str, Any]] = None
    ) -> None:
        current_trace = trace or self._playback_trace
        if not current_trace:
            return
        elapsed_ms = (
            time.perf_counter() - current_trace["started_at"]
        ) * 1000
        logging.info(
            "[PlaybackTiming] "
            f"trace={current_trace['id']} "
            f"stage={stage} "
            f"elapsed_ms={elapsed_ms:.2f} "
            f"service={current_trace['service']} "
            f"track={current_trace['track']!r}"
        )
        if stage == "playback-restart":
            self._log_playback_total(current_trace)

    def _log_playback_total(self, trace: Dict[str, Any]) -> None:
        context = trace["timing_context"]
        if not context or trace["summary_logged"]:
            return
        trace["summary_logged"] = True
        total_ms = (time.perf_counter() - context["started_at"]) * 1000
        kind = context["kind"]
        details = f"query={context['query']!r} " if kind == "search" else ""
        logging.info(
            f"[PlaybackTiming] {kind}_to_playback_completed "
            f"total_ms={total_ms:.2f} {details}"
            f"service={trace['service']} track={trace['track']!r}"
        )

    def _on_engine_event(self, event_name: str) -> None:
        self._log_playback_timing(event_name)
        if event_name == "playback-restart":
            if self._refresh_in_progress:
                # Keep the "already refreshed" mark so a stream that keeps
                # failing is not refreshed forever.
                self._refresh_in_progress = False
            else:
                self.track._stream_refresh_attempted = False

    def _sync_index_list(self) -> None:
        if self.mode == Mode.Random:
            if not hasattr(self, "_index_list") or not self._index_list:
                self.shuffle(True, preserve_current=True)
            elif len(self._index_list) < len(self.track_list):
                existing = set(self._index_list)
                missing = [i for i in range(len(self.track_list)) if i not in existing]
                random.shuffle(missing)
                self._index_list.extend(missing)

    def _prefetch_next_track(self) -> None:
        if not self._prefetch_lock.acquire(blocking=False):
            logging.info("[PlaybackTiming] next_track_prefetch_skipped reason=already_running")
            return
        started_at = time.perf_counter()
        try:
            # Se há faixa na fila, ela será a próxima — prefetch dela
            next_from_queue = self.queue.peek_next()
            if next_from_queue is not None:
                if not next_from_queue._is_fetched:
                    logging.info(f"Prefetching next track from queue: {next_from_queue.name}")
                    _ = next_from_queue.url
                    elapsed_ms = (time.perf_counter() - started_at) * 1000
                    logging.info(
                        "[PlaybackTiming] next_track_prefetch_completed "
                        f"elapsed_ms={elapsed_ms:.2f} source=queue "
                        f"service={next_from_queue.service} "
                        f"track={next_from_queue.name!r}"
                    )
                return

            if not self.track_list:
                return

            next_index = -1
            if self.mode == Mode.Random:
                self._sync_index_list()
                try:
                    current_pos = self._index_list.index(self.track_index)
                    if current_pos + 1 < len(self._index_list):
                        next_index = self._index_list[current_pos + 1]
                    elif len(self._index_list) > 0:
                        next_index = self._index_list[0]
                except (ValueError, IndexError, AttributeError):
                    pass
            elif self.mode == Mode.RepeatTrack:
                next_index = self.track_index
            else:
                if self.track_index + 1 < len(self.track_list):
                    next_index = self.track_index + 1
                elif self.mode == Mode.RepeatTrackList and len(self.track_list) > 0:
                    next_index = 0

            if next_index != -1 and next_index < len(self.track_list):
                next_track = self.track_list[next_index]
                if not next_track._is_fetched:
                    logging.info(f"Prefetching next track: {next_track.name}")
                    _ = next_track.url
                    elapsed_ms = (time.perf_counter() - started_at) * 1000
                    logging.info(
                        "[PlaybackTiming] next_track_prefetch_completed "
                        f"elapsed_ms={elapsed_ms:.2f} source=track_list "
                        f"service={next_track.service} track={next_track.name!r}"
                    )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            logging.warning(
                "[PlaybackTiming] next_track_prefetch_failed "
                f"elapsed_ms={elapsed_ms:.2f} error={e!r}"
            )
        finally:
            self._prefetch_lock.release()

    def play_from_queue(self, started_at: Optional[float] = None) -> bool:
        started_at = started_at or time.perf_counter()
        next_track = self.queue.pop_next()
        if next_track is None:
            return False

        logging.info(f"Playing from queue: {next_track.name}")
        self.track_list = [next_track]
        self.track_index = 0
        self.track = next_track
        self._set_next_playback_context(started_at)
        self._play(next_track.url)
        self.state = State.Playing
        self._log_next_track_completed(started_at, "queue")
        return True

    def _get_track_video_id(self, track: Optional[Track]) -> Optional[str]:
        if not track:
            return None
        info = getattr(track, "extra_info", None) or {}
        vid = info.get("videoId") or info.get("id") or info.get("contentId")
        if vid:
            return str(vid)
        url = getattr(track, "_url", "")
        if url:
            if "v=" in url:
                return url.split("v=")[1].split("&")[0].split("?")[0]
            elif "youtu.be" in url:
                return url.split("/")[-1].split("?")[0]
        return None

    def _check_and_trigger_autoplay(self) -> None:
        try:
            if not self.track_list or self.mode == Mode.SingleTrack or self.is_playlist:
                return
            remaining = len(self.track_list) - 1 - self.track_index
            if remaining <= 4:
                candidates = []
                if self.track:
                    candidates.append(self.track)
                for t in reversed(self.track_list):
                    if t not in candidates:
                        candidates.append(t)

                for cand in candidates:
                    target_id = self._get_track_video_id(cand)
                    if target_id:
                        service_name = getattr(cand, "service", None) or self.bot.service_manager.service.name
                        service = self.bot.service_manager.get_service_by_name(service_name)
                        if hasattr(service, "_fetch_autoplay_async"):
                            service._fetch_autoplay_async(target_id)
                            break
        except Exception as e:
            logging.debug(f"[Player] Autoplay check trigger error: {e}")

    def _replenish_autoplay_sync(self) -> bool:
        try:
            if not self.track_list or self.mode == Mode.SingleTrack or self.is_playlist:
                return False
            candidates = []
            if self.track:
                candidates.append(self.track)
            for t in reversed(self.track_list):
                if t not in candidates:
                    candidates.append(t)

            for cand in candidates:
                target_id = self._get_track_video_id(cand)
                if target_id:
                    service_name = getattr(cand, "service", None) or self.bot.service_manager.service.name
                    service = self.bot.service_manager.get_service_by_name(service_name)
                    if hasattr(service, "_fetch_autoplay_sync"):
                        if service._fetch_autoplay_sync(target_id):
                            return True
        except Exception as e:
            logging.warning(f"[Player] Sync autoplay replenishment error: {e}")
        return False

    def next(self) -> None:
        with self._navigation_lock:
            self._next_locked()

    def _next_locked(self) -> None:
        started_at = time.perf_counter()
        previous_track = self.track.name or "Unknown"
        logging.info(
            "[PlaybackTiming] next_track_started "
            f"previous_track={previous_track!r} queue_size={self.queue.size}"
        )
        if not self.queue.is_empty:
            if self.play_from_queue(started_at):
                return

        track_index = self.track_index
        if len(self.track_list) > 0:
            if self.mode == Mode.Random:
                self._sync_index_list()
                try:
                    current_position = self._index_list.index(self.track_index)
                    if current_position + 1 < len(self._index_list):
                        track_index = self._index_list[current_position + 1]
                    else:
                        if self.is_playlist and self.mode != Mode.RepeatTrackList:
                            raise errors.NoNextTrackError()
                        self.shuffle(True)
                        track_index = self._index_list[0] if self._index_list else 0
                except (IndexError, ValueError, AttributeError):
                    if self.is_playlist and self.mode != Mode.RepeatTrackList:
                        raise errors.NoNextTrackError()
                    self.shuffle(True)
                    track_index = self._index_list[0] if self._index_list else 0
            else:
                track_index += 1
        else:
            track_index = 0

        if track_index >= len(self.track_list):
            if self.mode == Mode.RepeatTrackList:
                self._set_next_playback_context(started_at)
                self.play_by_index(0)
                self._log_next_track_completed(started_at, "repeat_track_list")
                return
            if not self.is_playlist:
                self._replenish_autoplay_sync()
            if track_index >= len(self.track_list):
                raise errors.NoNextTrackError()

        try:
            self._set_next_playback_context(started_at)
            self.play_by_index(track_index)
            self._log_next_track_completed(started_at, "track_list")
        except errors.IncorrectTrackIndexError:
            if self.mode == Mode.RepeatTrackList:
                self._set_next_playback_context(started_at)
                self.play_by_index(0)
                self._log_next_track_completed(started_at, "repeat_track_list")
            elif self.mode == Mode.Random and not self.is_playlist:
                self.shuffle(True)
                self._set_next_playback_context(started_at)
                self.play_by_index(self._index_list[0] if self._index_list else 0)
                self._log_next_track_completed(started_at, "random")
            else:
                raise errors.NoNextTrackError()

    def _set_next_playback_context(self, started_at: float) -> None:
        self._pending_playback_context = {
            "kind": "next_track",
            "started_at": started_at,
        }

    def _log_next_track_completed(self, started_at: float, source: str) -> None:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logging.info(
            "[PlaybackTiming] next_track_submitted "
            f"elapsed_ms={elapsed_ms:.2f} source={source} "
            f"service={self.track.service} track={self.track.name!r}"
        )

    def previous(self) -> None:
        track_index = self.track_index
        if len(self.track_list) > 0:
            if self.mode == Mode.Random:
                self._sync_index_list()
                try:
                    current_position = self._index_list.index(self.track_index)
                    if current_position > 0:
                        track_index = self._index_list[current_position - 1]
                    else:
                        track_index = self._index_list[-1]
                except (IndexError, ValueError, AttributeError):
                    track_index = self.track_index
            else:
                if track_index == 0 and self.mode != Mode.RepeatTrackList:
                    raise errors.NoPreviousTrackError
                else:
                    track_index -= 1
        else:
            track_index = 0
        try:
            self.play_by_index(track_index)
        except errors.IncorrectTrackIndexError:
            if self.mode == Mode.RepeatTrackList:
                self.play_by_index(len(self.track_list) - 1)
            else:
                raise errors.NoPreviousTrackError

    def play_by_index(self, index: int) -> None:
        if index < len(self.track_list) and index >= (0 - len(self.track_list)):
            self.track = self.track_list[index]
            self.track_index = index if index >= 0 else len(self.track_list) + index
            try:
                self._play(self.track.url)
                self.state = State.Playing
                self._check_and_trigger_autoplay()
            except errors.ServiceError as e:
                logging.warning(f"[Player] Track '{self.track.name}' is unplayable ({e}). Auto-skipping to next track...")
                if self.mode != Mode.SingleTrack and len(self.track_list) > index + 1:
                    self.next()
                else:
                    raise
        else:
            raise errors.IncorrectTrackIndexError()

    def set_volume(self, volume: int) -> None:
        volume = volume if volume <= self.config.max_volume else self.config.max_volume
        self.volume = volume
        if self.config.volume_fading:
            current = int(self._engine.volume)
            n = 1 if current < volume else -1
            for i in range(current, volume, n):
                self._engine.volume = i
                time.sleep(self.config.volume_fading_interval)
        self._engine.volume = volume

    def _is_seekable_source(self) -> bool:
        """Streams whose length FFmpeg cannot report are only seeked when the
        track is known not to be a live stream."""
        return self.track.type not in (TrackType.Live, TrackType.Direct)

    def get_speed(self) -> float:
        return self._engine.speed

    def set_speed(self, arg: float) -> None:
        if arg < 0.25 or arg > 4:
            raise ValueError()
        self._engine.set_speed(arg, force=self._is_seekable_source())

    def seek_back(self, step: Optional[float] = None) -> None:
        step = step if step else self.config.seek_step
        if step <= 0:
            raise ValueError()
        self._engine.seek(-step, force=self._is_seekable_source())

    def seek_forward(self, step: Optional[float] = None) -> None:
        step = step if step else self.config.seek_step
        if step <= 0:
            raise ValueError()
        self._engine.seek(step, force=self._is_seekable_source())

    def get_duration(self) -> float:
        duration = self._engine.duration
        return duration if duration is not None else 0.0

    def get_position(self) -> float:
        return self._engine.position

    def shuffle(self, enable: bool, preserve_current: bool = False) -> None:
        if enable:
            if not self.track_list:
                self._index_list = []
                return
            indices = list(range(len(self.track_list)))
            if preserve_current and self.track_index in indices:
                indices.remove(self.track_index)
                random.shuffle(indices)
                self._index_list = [self.track_index] + indices
            else:
                random.shuffle(indices)
                self._index_list = indices
            logging.info(f"[Player] Shuffled playlist of {len(self.track_list)} tracks 100% randomly (preserve_current={preserve_current}). First picked track index: {self._index_list[0] if self._index_list else None}")
        else:
            if hasattr(self, "_index_list"):
                del self._index_list

    def _parse_metadata(self, metadata: Dict[str, Any]) -> str:
        stream_names = ["icy-name"]
        stream_name = None
        title = None
        artist = None
        for i in metadata:
            if i in stream_names:
                stream_name = html.unescape(metadata[i])
            if "title" in i.lower():
                title = html.unescape(metadata[i])
            if "artist" in i.lower():
                artist = html.unescape(metadata[i])
        chunks: List[str] = []
        chunks.append(artist) if artist else ...
        chunks.append(title) if title else ...
        chunks.append(stream_name) if stream_name else ...
        return " - ".join(chunks)

    def on_end_file(self, reason: str, error: str = "") -> None:
        """Called by the FFmpeg engine (on its own thread) when a stream ends
        by itself: ``eof`` for a normal end, ``error`` when it failed."""
        if (
            reason == END_ERROR
            and self.track.service in ("yt", "ytm")
            and not getattr(self.track, "_stream_refresh_attempted", False)
        ):
            self.track._stream_refresh_attempted = True
            try:
                logging.warning(
                    "[PlaybackTiming] youtube_stream_refresh_started "
                    f"track={self.track.name!r} error={error[:200]!r}"
                )
                resume_at = self._engine.last_position
                if resume_at < RESUME_AFTER_ERROR_MIN_SECONDS:
                    resume_at = 0.0
                refreshed_url = self.track.refresh_stream()
                self._play(
                    refreshed_url,
                    save_to_recents=False,
                    start_position=resume_at,
                    is_refresh=True,
                )
                return
            except Exception as refresh_error:
                logging.error(
                    "[PlaybackTiming] youtube_stream_refresh_failed "
                    f"track={self.track.name!r} error={refresh_error!r}"
                )
        if self.state == State.Playing and self._engine.idle:
            if self.mode == Mode.SingleTrack or self.track.type == TrackType.Direct:
                # Mesmo em SingleTrack/Direct, a fila tem prioridade
                if not self.queue.is_empty:
                    self.play_from_queue()
                else:
                    self.stop()
            elif self.mode == Mode.RepeatTrack:
                # RepeatTrack repete a atual — fila NÃO interrompe automaticamente
                # O usuário pode usar 'qs' para pular para a fila manualmente
                self.play_by_index(self.track_index)
            else:
                # Para todos os outros modos, a fila tem prioridade
                if not self.queue.is_empty:
                    self.play_from_queue()
                else:
                    try:
                        self.next()
                    except errors.NoNextTrackError:
                        self.stop()

    def on_metadata_update(self, name: str, value: Any) -> None:
        if self._engine.idle:
            return
        if self.track.type == TrackType.Direct or self.track.type == TrackType.Local:
            metadata = self._engine.metadata
            media_title = html.unescape(self._engine.media_title)
            try:
                new_name = self._parse_metadata(metadata)
                if not new_name:
                    new_name = media_title
            except TypeError:
                new_name = media_title
            if new_name and self.track.name != new_name:
                self.track.name = new_name
