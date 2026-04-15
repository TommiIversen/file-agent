"""
Audio Recording — Callback Adapter

Bridges the sync ``RecorderCallback`` protocol (called from recorder threads)
into the async ``DomainEventBus`` world using ``loop.call_soon_threadsafe``.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional

from app.core.events.audio_events import (
    AudioDeviceDisconnectedEvent,
    AudioLevelsEvent,
    AudioOverflowWarningEvent,
    AudioRecordingErrorEvent,
    AudioRecordingStartedEvent,
    AudioRecordingStoppedEvent,
)
from app.core.events.event_bus import DomainEventBus

logger = logging.getLogger(__name__)


class RecorderEventAdapter:
    """Implements ``RecorderCallback`` and publishes domain events.

    Must be constructed on the asyncio event loop thread so that
    ``_loop`` is valid for ``call_soon_threadsafe``.
    """

    def __init__(
        self,
        event_bus: DomainEventBus,
        device_name: str,
        session_id: Optional[str] = None,
    ) -> None:
        self._event_bus = event_bus
        self._device_name = device_name
        self._session_id = session_id
        self._loop = asyncio.get_running_loop()

    def set_session_id(self, session_id: str) -> None:
        self._session_id = session_id

    # ── RecorderCallback implementation ────────────────────────

    def on_started(self, files: list[Path], actual_samplerate: float) -> None:
        self._fire(
            AudioRecordingStartedEvent(
                session_id=self._session_id or "",
                tracks=[f.stem for f in files],
                samplerate=int(actual_samplerate),
                files=[str(f) for f in files],
            )
        )

    def on_stopped(
        self,
        files: list[Path],
        duration_seconds: float,
        overflow_count: int,
    ) -> None:
        self._fire(
            AudioRecordingStoppedEvent(
                session_id=self._session_id or "",
                files=[str(f) for f in files],
                duration_seconds=duration_seconds,
                overflow_count=overflow_count,
            )
        )

    def on_error(self, error_message: str, recoverable: bool) -> None:
        logger.error("Audio recording error: %s (recoverable=%s)", error_message, recoverable)
        self._fire(
            AudioRecordingErrorEvent(
                error=error_message,
                recoverable=recoverable,
                session_id=self._session_id,
            )
        )

    def on_overflow_warning(self, dropped_count: int, total_drops: int) -> None:
        self._fire(
            AudioOverflowWarningEvent(
                dropped_count=dropped_count,
                total_drops=total_drops,
                session_id=self._session_id,
            )
        )

    def on_device_lost(self) -> None:
        logger.error("Audio device lost: %s", self._device_name)
        self._fire(AudioDeviceDisconnectedEvent(device_name=self._device_name))

    def on_levels(self, track_peaks: list[dict[str, Any]]) -> None:
        import time as _time
        t0 = _time.perf_counter()
        self._fire(
            AudioLevelsEvent(
                session_id=self._session_id or "",
                track_peaks=track_peaks,
            )
        )
        dt = (_time.perf_counter() - t0) * 1000
        if dt > 1:
            logger.debug("levels: adapter._fire took %.1fms", dt)

    # ── Thread-safe bridge ─────────────────────────────────────

    def _fire(self, event) -> None:
        """Schedule async event publication from any thread."""
        try:
            self._loop.call_soon_threadsafe(
                asyncio.ensure_future,
                self._event_bus.publish(event),
            )
        except RuntimeError:
            # Event loop closed (shutdown)
            logger.debug("Event loop closed — dropping event %s", type(event).__name__)
