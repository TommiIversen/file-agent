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
from .recorder.factory import create_recorder, list_available_devices
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
        self._device_name: Optional[str] = None  # remember for re-creation

    # ── Initialization ─────────────────────────────────────────

    def set_recorder(self, recorder: AudioRecorder) -> None:
        """Inject the platform-specific recorder (called from DI)."""
        self._recorder = recorder
        self._device_name = getattr(recorder, "_device_name", None)

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
            # If recorder was lost, try to re-create it on-demand
            if self._recorder is None and self._device_name:
                logger.info("Recorder not available — attempting on-demand re-creation")
                loop = asyncio.get_running_loop()
                try:
                    self._recorder = await loop.run_in_executor(
                        None,
                        lambda: create_recorder(self._device_name, reinit_portaudio=True),
                    )
                    logger.info("On-demand recorder re-creation succeeded")
                except Exception:
                    logger.error(
                        "On-demand recorder re-creation failed for '%s'",
                        self._device_name,
                        exc_info=True,
                    )

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
            "track_count": self._recorder.track_count,
            "samplerate": self._recorder.samplerate,
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

    # ── Device-loss recovery ───────────────────────────────────

    async def invalidate_recorder(self) -> None:
        """Mark the recorder as dead without re-creating it.

        Called immediately on device disconnect.  Re-creation happens
        later via ``handle_device_lost()`` once the device reappears.
        """
        async with self._lock:
            self._current_files = []
            self._current_session_id = None
            self._recorder = None

    async def handle_device_lost(self) -> None:
        """Invalidate dead recorder and re-create with PortAudio reinit.

        Should be called AFTER the device has reappeared in the OS
        device list, so PortAudio reinit succeeds.
        """
        async with self._lock:
            self._current_files = []
            self._current_session_id = None
            self._recorder = None  # discard the dead instance

            if not self._device_name:
                logger.warning("No device name stored — cannot attempt re-creation")
                return

            logger.info(
                "Attempting to re-create recorder for device '%s'",
                self._device_name,
            )
            loop = asyncio.get_running_loop()
            try:
                recorder = await loop.run_in_executor(
                    None,
                    lambda: create_recorder(self._device_name, reinit_portaudio=True),
                )
                self._recorder = recorder
                logger.info(
                    "Recorder re-created successfully for '%s'",
                    self._device_name,
                )
            except Exception:
                logger.warning(
                    "Could not re-create recorder for '%s' — "
                    "will retry on next recording start",
                    self._device_name,
                    exc_info=True,
                )

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
