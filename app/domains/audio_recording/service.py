"""
Audio Recording — Recording Service

Orchestrates the recorder engine: start/stop, settings resolution,
recovery-postfix management, and the async bridge via RecorderEventAdapter.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.events.event_bus import DomainEventBus

from .callback_adapter import RecorderEventAdapter
from .recorder.base import AudioRecorder
from .recorder.factory import list_available_devices
from .recorder.models import AudioTrack, DeviceInfo

logger = logging.getLogger(__name__)


class AudioRecordingService:
    """Thin orchestrator — owns one ``AudioRecorder`` instance and a lock."""

    def __init__(
        self,
        event_bus: DomainEventBus,
    ) -> None:
        self._event_bus = event_bus
        self._recorder: Optional[AudioRecorder] = None
        self._adapter: Optional[RecorderEventAdapter] = None
        self._lock = asyncio.Lock()

        # Recovery postfix counter (per session prefix)
        self._recovery_counters: Dict[str, int] = {}
        self._current_session_id: Optional[str] = None
        self._current_files: List[Path] = []

    # ── Initialization ─────────────────────────────────────────

    def set_recorder(self, recorder: AudioRecorder) -> None:
        """Inject the platform-specific recorder (called from DI)."""
        self._recorder = recorder

    # ── Start / Stop ───────────────────────────────────────────

    async def start(
        self,
        session_id: str,
        filename_stem: str,
        channel_name: Optional[str],
        tracks: list[AudioTrack],
        samplerate: int,
        output_dir: Path,
    ) -> list[Path]:
        async with self._lock:
            if self._recorder is None:
                raise RuntimeError("No recorder configured — check audio settings")

            if self._recorder.is_recording:
                logger.debug("Already recording — ignoring start request")
                return self._current_files

            # Wire callback adapter
            self._adapter = RecorderEventAdapter(
                event_bus=self._event_bus,
                device_name=getattr(self._recorder, "_device_name", "unknown"),
                session_id=session_id,
            )
            self._recorder.set_callback(self._adapter)
            self._current_session_id = session_id

            # Start on a thread (ASIO start is blocking)
            loop = asyncio.get_running_loop()
            files = await loop.run_in_executor(
                None,
                self._recorder.start,
                tracks,
                samplerate,
                output_dir,
                filename_stem,
                channel_name,
            )
            self._current_files = files
            return files

    async def stop(self) -> dict:
        async with self._lock:
            if self._recorder is None or not self._recorder.is_recording:
                return {"status": "not_recording"}

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, self._recorder.stop)
            self._current_files = []
            self._current_session_id = None
            return result

    # ── Queries ────────────────────────────────────────────────

    @property
    def is_recording(self) -> bool:
        return self._recorder is not None and self._recorder.is_recording

    def get_status(self) -> Dict[str, Any]:
        if self._recorder is None:
            return {"recording": False, "configured": False}
        return {
            "recording": self._recorder.is_recording,
            "configured": True,
            "duration_seconds": self._recorder.duration_seconds,
            "overflow_count": self._recorder.overflow_count,
            "session_id": self._current_session_id,
            "files": [str(f) for f in self._current_files],
        }

    async def list_devices(self) -> list[DeviceInfo]:
        loop = asyncio.get_running_loop()
        if self._recorder is not None:
            return await loop.run_in_executor(None, self._recorder.list_devices)
        return await loop.run_in_executor(None, list_available_devices)

    # ── Recovery postfix ───────────────────────────────────────

    def get_recovery_prefix(self, base_prefix: str) -> str:
        """Return ``base_prefix`` on first use, ``base_prefix_rec2`` on second, etc."""
        count = self._recovery_counters.get(base_prefix, 0) + 1
        self._recovery_counters[base_prefix] = count
        if count == 1:
            return base_prefix
        return f"{base_prefix}_rec{count}"

    def reset_recovery_counter(self) -> None:
        self._recovery_counters.clear()

    # ── Reinitialize (settings change) ─────────────────────────

    async def reinitialize(self, recorder: AudioRecorder) -> None:
        """Replace the recorder instance (e.g. after device/samplerate change).

        Only allowed when NOT recording.
        """
        async with self._lock:
            if self._recorder is not None and self._recorder.is_recording:
                raise RuntimeError("Cannot reinitialize while recording")
            self._recorder = recorder

    # ── Shutdown ───────────────────────────────────────────────

    async def shutdown(self) -> None:
        """Clean shutdown — stop recording if active, release platform resources."""
        if self.is_recording:
            logger.warning("Shutting down with active recording — stopping cleanly")
            await self.stop()

        # Release platform audio driver (e.g. ASIO COM thread on Windows)
        import sys

        if sys.platform == "win32":
            try:
                from .recorder.asio_recorder import shutdown_asio

                shutdown_asio()
                logger.info("ASIO thread shutdown completed")
            except Exception:
                logger.debug("ASIO shutdown skipped (not initialized)", exc_info=True)
