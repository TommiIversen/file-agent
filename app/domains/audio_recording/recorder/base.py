"""
Audio Recording — Abstract Recorder Base Class

Platform-independent interface + shared recording machinery.
Subclasses (AsioRecorder, CoreAudioRecorder) only implement stream open/close
and device listing.
"""

from __future__ import annotations

import logging
import queue
import shutil
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

import numpy as np

from .callback import RecorderCallback
from .models import AudioTrack, DeviceInfo

logger = logging.getLogger(__name__)

# If no audio callback arrives within this window,
# the device is presumed lost.  At 48 kHz / 128 frames per block
# callbacks arrive every ~2.7 ms — 500 ms is extremely conservative.
_WATCHDOG_TIMEOUT_S = 0.5
_WATCHDOG_CHECK_INTERVAL_S = 0.25

# How often the watchdog verifies the device is still present in the
# system device list.  On macOS, CoreAudio silently re-routes to the
# default device on USB unplug — the callback keeps running with stale
# data, so silence/callback-timeout detection is insufficient.
_DEVICE_CHECK_INTERVAL_S = 2.0

MAX_QUEUE_SIZE = 4096
_MIN_DISK_SPACE_BYTES = 1_073_741_824  # 1 GB pre-flight check

# Target ~10 Hz level updates = ~100 ms between emissions.
# Frame count is samplerate-independent: derived in start() as samplerate // 10.
_LEVELS_INTERVAL_FRAMES_DEFAULT = 4800  # fallback: 48000 / 10


class _TrackWriter:
    """Holds a soundfile writer + its track metadata."""

    __slots__ = ("track", "path", "writer")

    def __init__(self, track: AudioTrack, path: Path, writer: Any) -> None:
        self.track = track
        self.path = path
        self.writer = writer


class AudioRecorder(ABC):
    """Abstract recorder that all platform backends extend.

    Shared machinery: audio callback, writer thread, queue, zero-fill,
    WAV file creation, atomic rollback, watchdog.

    Subclasses implement:
        ``_open_stream()`` → float (actual samplerate)
        ``_close_stream()`` → None
        ``_resolve_device()`` → None (set ``_device_index``)
        ``list_devices()`` → list[DeviceInfo]
    """

    def __init__(self, device_name: str) -> None:
        self._device_name = device_name
        self._callback: Optional[RecorderCallback] = None
        self._recording = False
        self._start_time: Optional[float] = None
        self._overflow_count = 0

        # Audio pipeline
        self._audio_q: queue.Queue[tuple[np.ndarray, int] | None] = queue.Queue(
            maxsize=MAX_QUEUE_SIZE,
        )
        self._stream: Any = None
        self._track_writers: list[_TrackWriter] = []
        self._writer_thread: Optional[threading.Thread] = None
        self._writer_error: Optional[BaseException] = None
        self._dropped_since_last = 0

        # Channel mapping — built by _build_channel_map()
        self._channel_selectors: list[int] = []
        self._channel_map: list[tuple[int, int]] = []
        self._track_cols: list[list[int]] = []
        self._samplerate = 0

        # Watchdog bookkeeping
        self._last_callback_time: float = 0.0
        self._watchdog_thread: Optional[threading.Thread] = None
        self._watchdog_stop = threading.Event()

        # Guard for _handle_device_lost (may be called from multiple threads)
        self._device_lost_lock = threading.Lock()

        # Peak metering
        self._peak_acc: Optional[np.ndarray] = None
        self._levels_frame_count = 0
        self._levels_interval_frames = _LEVELS_INTERVAL_FRAMES_DEFAULT

    # ── Callback wiring ──────────────────────────────────────────

    def set_callback(self, cb: RecorderCallback) -> None:
        self._callback = cb

    # ── Public interface ─────────────────────────────────────────

    def start(
        self,
        tracks: list[AudioTrack],
        samplerate: int,
        output_dir: Path,
        filename_stem: str,
        channel_name: Optional[str] = None,
    ) -> list[Path]:
        """Start recording.  Returns the list of WAV file paths created.

        When *channel_name* is provided and appears in *filename_stem*,
        each track's filename is built by replacing the channel portion with
        the track label (naming-convention-agnostic).  Otherwise, the label
        is appended: ``{stem}_{label}.wav``.
        """
        if self._recording:
            raise RuntimeError("Already recording")

        # Pre-flight: disk space check
        free = shutil.disk_usage(output_dir).free
        if free < _MIN_DISK_SPACE_BYTES:
            raise OSError(
                f"Insufficient disk space: {free / (1024**3):.1f} GB free, "
                f"need at least {_MIN_DISK_SPACE_BYTES / (1024**3):.1f} GB"
            )

        self._resolve_device()
        self._samplerate = samplerate
        self._build_channel_map(tracks)

        # Reset state
        self._overflow_count = 0
        self._writer_error = None
        self._dropped_since_last = 0
        self._drain_queue()
        self._peak_acc = np.zeros(len(self._channel_selectors), dtype=np.float32)
        self._levels_frame_count = 0
        self._levels_interval_frames = samplerate // 10

        output_dir.mkdir(parents=True, exist_ok=True)

        # Create WAV files
        created_files = self._create_wav_files(
            tracks, samplerate, output_dir, filename_stem, channel_name
        )

        # Start writer thread
        self._writer_thread = threading.Thread(
            target=self._writer_loop, name="wav-writer"
        )
        self._writer_thread.start()

        # Start audio stream (subclass-specific)
        try:
            actual_sr = self._open_stream()
        except Exception:
            self._abort_writer_and_cleanup(created_files)
            raise

        if actual_sr != samplerate:
            self._close_stream()
            self._abort_writer_and_cleanup(created_files)
            raise RuntimeError(
                f"Samplerate mismatch: requested {samplerate}, got {actual_sr}. "
                "Check your audio device settings."
            )

        self._recording = True
        self._start_time = time.monotonic()
        self._start_watchdog()

        if self._callback:
            self._callback.on_started(created_files, actual_sr)

        return created_files

    def stop(self) -> dict:
        """Stop recording.  Returns a status dict."""
        if not self._recording:
            return {"status": "not_recording"}

        duration = self.duration_seconds
        self._recording = False
        self._stop_watchdog()

        self._close_stream()

        # Signal writer thread to drain and stop
        self._audio_q.put(None)
        if self._writer_thread is not None:
            self._writer_thread.join(timeout=10)
            self._writer_thread = None

        files = [tw.path for tw in self._track_writers]
        self._close_writers()

        result: dict[str, Any] = {
            "status": "stopped",
            "overflow_count": self._overflow_count,
            "duration_seconds": duration,
        }
        if self._writer_error:
            result["writer_error"] = str(self._writer_error)

        if self._callback:
            self._callback.on_stopped(files, duration, self._overflow_count)

        self._start_time = None
        self._peak_acc = None
        self._levels_frame_count = 0
        return result

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def duration_seconds(self) -> float:
        if self._start_time is None:
            return 0.0
        return time.monotonic() - self._start_time

    @property
    def overflow_count(self) -> int:
        return self._overflow_count

    @property
    def track_count(self) -> int:
        return len(self._track_writers)

    @property
    def samplerate(self) -> int:
        return self._samplerate

    @abstractmethod
    def list_devices(self) -> list[DeviceInfo]:
        """Return available audio input devices for this platform."""
        ...

    # ── Subclass hooks ───────────────────────────────────────────

    @abstractmethod
    def _open_stream(self) -> float:
        """Open the platform audio stream.  Return actual samplerate."""
        ...

    @abstractmethod
    def _close_stream(self) -> None:
        """Close the platform audio stream."""
        ...

    @abstractmethod
    def _resolve_device(self) -> None:
        """Resolve device name to platform index.  Called before start."""
        ...

    def _is_device_present(self) -> bool:
        """Check if the configured device is still visible to the OS.

        Subclasses MAY override for a cheaper/platform-specific check.
        The default scans ``list_devices()`` for ``_device_name``.
        """
        try:
            return any(
                self._device_name.lower() in d.name.lower()
                for d in self.list_devices()
            )
        except Exception:
            return False

    # ── Audio callback (shared) ──────────────────────────────────

    def _callback_fn(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        """Audio callback — runs on the audio driver thread."""
        self._touch_watchdog()

        if not self._recording:
            return
        if status:
            logger.warning("Audio callback status: %s", status)
            # PortAudio sets 'input overflow' / 'input underflow' flags
            # when the device can't deliver data.  A single flag is normal
            # (transient glitch), but we don't abort here — the
            # finished_callback / watchdog handle actual device loss.

        try:
            self._audio_q.put_nowait((indata.copy(), self._dropped_since_last))
            self._dropped_since_last = 0
        except queue.Full:
            self._dropped_since_last += 1
            self._overflow_count += 1
            if self._overflow_count % 100 == 1:
                logger.error(
                    "Audio queue overflow #%d — writer can't keep up",
                    self._overflow_count,
                )
                if self._callback:
                    self._callback.on_overflow_warning(
                        self._dropped_since_last, self._overflow_count
                    )

    # ── Writer thread (shared) ───────────────────────────────────

    def _writer_loop(self) -> None:
        try:
            while True:
                item = self._audio_q.get()
                if item is None:
                    break
                block, dropped_count = item

                # Zero-fill dropped blocks to maintain timeline sync
                if dropped_count > 0:
                    frames_per_block = block.shape[0]
                    for tw in self._track_writers:
                        num_ch = len(tw.track.channels)
                        silence = np.zeros(
                            (frames_per_block * dropped_count, num_ch),
                            dtype=block.dtype,
                        )
                        tw.writer.write(silence)

                # Demux from interleaved block to per-track WAV files
                for tw, cols in zip(self._track_writers, self._track_cols):
                    if len(cols) == 1:
                        tw.writer.write(block[:, cols[0]])
                    else:
                        tw.writer.write(block[:, cols])

                # Peak metering (~2.5 µs per block — negligible)
                if self._peak_acc is not None and self._callback:
                    col_peaks = np.abs(block).max(axis=0)
                    np.maximum(self._peak_acc, col_peaks, out=self._peak_acc)
                    self._levels_frame_count += block.shape[0]
                    if self._levels_frame_count >= self._levels_interval_frames:
                        track_peaks: list[dict[str, Any]] = []
                        for tw2, cols2 in zip(self._track_writers, self._track_cols):
                            track_peaks.append({
                                "label": tw2.track.label,
                                "peaks": [round(float(self._peak_acc[c]), 4) for c in cols2],
                            })
                        self._callback.on_levels(track_peaks)
                        self._peak_acc[:] = 0.0
                        self._levels_frame_count = 0

        except OSError as exc:
            self._writer_error = exc
            self._recording = False
            logger.exception("Writer thread disk error (likely full)")
            if self._callback:
                self._callback.on_error(str(exc), recoverable=False)
        except Exception as exc:
            self._writer_error = exc
            self._recording = False
            logger.exception("Writer thread fatal error")
            if self._callback:
                self._callback.on_error(str(exc), recoverable=False)

    # ── Channel mapping ──────────────────────────────────────────

    def _build_channel_map(self, tracks: list[AudioTrack]) -> None:
        """Build ``_channel_selectors`` and ``_channel_map`` from tracks.

        ``_channel_selectors``: flat list of 0-based HW channel indices.
        ``_channel_map``: for each flat index → (track_writer_index, sub_channel).
        """
        self._channel_selectors = []
        self._channel_map = []
        tw_index = 0
        for track in tracks:
            for sub_ch, hw_ch in enumerate(track.channels):
                self._channel_selectors.append(hw_ch - 1)  # 1-based → 0-based
                self._channel_map.append((tw_index, sub_ch))
            tw_index += 1

        # Precompute per-track column indices for the writer loop hot path
        self._track_cols = [
            [fi for fi, (tw, _) in enumerate(self._channel_map) if tw == ti]
            for ti in range(len(tracks))
        ]

    # ── WAV file creation ────────────────────────────────────────

    def _create_wav_files(
        self,
        tracks: list[AudioTrack],
        samplerate: int,
        output_dir: Path,
        filename_stem: str,
        channel_name: Optional[str] = None,
    ) -> list[Path]:
        import soundfile as sf

        self._track_writers = []
        created_files: list[Path] = []
        try:
            for track in tracks:
                num_channels = len(track.channels)
                name = self._build_track_filename(
                    filename_stem, channel_name, track.label
                )
                path = output_dir / name
                writer = sf.SoundFile(
                    str(path),
                    mode="w",
                    samplerate=samplerate,
                    channels=num_channels,
                    format="WAV",
                    subtype="PCM_24",
                )
                self._enable_header_auto_update(writer)
                self._track_writers.append(_TrackWriter(track, path, writer))
                created_files.append(path)
        except Exception:
            self._close_writers()
            self._remove_empty_files(created_files)
            raise
        return created_files

    @staticmethod
    def _build_track_filename(
        stem: str, channel_name: Optional[str], track_label: str
    ) -> str:
        """Build a WAV filename for a track.

        If *channel_name* appears in *stem*, replace it with *track_label*
        (naming-convention-agnostic).  Otherwise, append the label.
        """
        if channel_name and channel_name in stem:
            return stem.replace(channel_name, track_label, 1) + ".wav"
        return f"{stem}_{track_label}.wav"

    # ── Helpers ──────────────────────────────────────────────────

    def _abort_writer_and_cleanup(self, created_files: list[Path]) -> None:
        """Signal writer thread to stop, close writers, remove empty files."""
        self._audio_q.put(None)
        if self._writer_thread is not None:
            self._writer_thread.join(timeout=5)
        self._close_writers()
        self._remove_empty_files(created_files)

    def _drain_queue(self) -> None:
        while not self._audio_q.empty():
            try:
                self._audio_q.get_nowait()
            except queue.Empty:
                break

    def _close_writers(self) -> None:
        for tw in self._track_writers:
            try:
                tw.writer.close()
            except Exception:
                logger.exception("Error closing WAV file %s", tw.path)
        self._track_writers = []

    @staticmethod
    def _remove_empty_files(files: list[Path]) -> None:
        for f in files:
            try:
                if f.exists() and f.stat().st_size == 0:
                    f.unlink()
            except OSError:
                pass

    @staticmethod
    def _enable_header_auto_update(writer: Any) -> None:
        """Enable SFC_SET_UPDATE_HEADER_AUTO so the WAV header on disk
        is always current while recording."""
        try:
            import soundfile as sf

            sf._snd.sf_command(writer._file, 0x1061, sf._ffi.NULL, 1)
        except Exception:
            logger.debug(
                "Could not enable auto header update — WAV header will only "
                "be finalised on close",
                exc_info=True,
            )

    # ── Watchdog ─────────────────────────────────────────────────

    def _start_watchdog(self) -> None:
        self._last_callback_time = time.monotonic()
        self._last_device_check_time = time.monotonic()
        self._watchdog_stop.clear()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            name="audio-watchdog",
            daemon=True,
        )
        self._watchdog_thread.start()

    def _stop_watchdog(self) -> None:
        self._watchdog_stop.set()
        if self._watchdog_thread is not None:
            if self._watchdog_thread is not threading.current_thread():
                self._watchdog_thread.join(timeout=2)
            self._watchdog_thread = None

    def _watchdog_loop(self) -> None:
        while not self._watchdog_stop.is_set():
            self._watchdog_stop.wait(_WATCHDOG_CHECK_INTERVAL_S)
            if self._watchdog_stop.is_set():
                break
            if not self._recording:
                continue

            # Check 1: no audio callbacks arriving (device truly dead)
            elapsed = time.monotonic() - self._last_callback_time
            if elapsed > _WATCHDOG_TIMEOUT_S:
                logger.error(
                    "Audio watchdog: no callback for %.1f s — device presumed lost",
                    elapsed,
                )
                self._handle_device_lost()
                break

            # Check 2: device still in OS device list?
            # On macOS, CoreAudio silently re-routes to default device on
            # USB unplug — the callback keeps running with stale data.
            # This is the ONLY reliable detection for that scenario.
            now = time.monotonic()
            if now - self._last_device_check_time >= _DEVICE_CHECK_INTERVAL_S:
                self._last_device_check_time = now
                if not self._is_device_present():
                    logger.error(
                        "Audio watchdog: device '%s' no longer present — "
                        "device presumed lost",
                        self._device_name,
                    )
                    self._handle_device_lost()
                    break

    def _touch_watchdog(self) -> None:
        self._last_callback_time = time.monotonic()

    # ── Stream finished (device lost / aborted) ──────────────────

    def _on_stream_finished(self) -> None:
        """Called by PortAudio's ``finished_callback`` when the stream ends.

        On CoreAudio this fires immediately when a USB device is unplugged,
        even if the regular audio callback was still being invoked with
        stale data.  This is the *primary* device-loss detection mechanism;
        the watchdog is the *backup*.

        IMPORTANT: This runs on PortAudio's internal thread.  We MUST NOT
        call ``_close_stream()`` (which does ``stream.stop()``) here —
        that would deadlock because PortAudio is waiting for this callback
        to return.  Instead we schedule cleanup on a new thread.
        """
        if not self._recording:
            return  # Clean stop — ignore
        logger.error("Audio stream finished unexpectedly — device presumed lost")
        threading.Thread(
            target=self._handle_device_lost,
            name="audio-device-lost-cleanup",
            daemon=True,
        ).start()

    def _handle_device_lost(self) -> None:
        """Full cleanup after device loss — stream, writer, WAV files.

        Safe to call from any thread (watchdog, finished_callback spawned
        thread, etc.).  Serialised via ``_device_lost_lock`` and
        idempotent — a second call is a no-op.
        """
        with self._device_lost_lock:
            if not self._recording:
                return
            self._recording = False
            self._stop_watchdog()

        # 1. Close the audio stream (may already be dead).
        #    On a dead device this can raise — that's fine.
        try:
            self._close_stream()
        except Exception:
            logger.debug("Stream close during device-lost cleanup failed", exc_info=True)
            # Force-clear the reference so we don't hold a dead stream
            self._stream = None

        # 2. Signal writer thread to drain remaining queued data and stop
        try:
            self._audio_q.put_nowait(None)
        except queue.Full:
            pass
        if self._writer_thread is not None:
            self._writer_thread.join(timeout=5)
            self._writer_thread = None

        # 3. Close WAV files so data written so far is valid
        files = [tw.path for tw in self._track_writers]
        duration = self.duration_seconds
        self._close_writers()
        self._start_time = None
        self._peak_acc = None
        self._levels_frame_count = 0

        logger.info(
            "Device-lost cleanup complete: %d file(s), %.1f s recorded",
            len(files),
            duration,
        )

        # 4. Notify domain layer
        if self._callback:
            self._callback.on_stopped(files, duration, self._overflow_count)
            self._callback.on_device_lost()
