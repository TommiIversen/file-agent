"""
Audio Recording — Event Handlers

Listens to ingest_monitor events (via EventBus) to slave audio recording
to Justin's recording state.  Also handles AutoStopTriggeredEvent and
AudioDeviceDisconnectedEvent for recovery.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional

from app.core.cqrs.command_bus import CommandBus
from app.core.cqrs.query_bus import QueryBus
from app.core.cqrs.shared_queries import GetCurrentFilenameQuery
from app.core.events.audio_events import AudioDeviceDisconnectedEvent
from app.core.events.ingest_events import (
    AutoStopTriggeredEvent,
    ChannelRecordingStartedEvent,
    ChannelRecordingStoppedEvent,
)

from .commands import StartAudioRecordingCommand, StopAudioRecordingCommand
from .service import AudioRecordingService

logger = logging.getLogger(__name__)


class AudioRecordingEventHandler:
    """Reacts to Justin recording events and manages audio lifecycle.

    Start-flow:
        ChannelRecordingStartedEvent (first channel) → start audio
        Subsequent channel starts → ignored (already recording)

    Stop-flow:
        All channels stopped → stop audio

    Justin down:
        Audio continues — auto-stop is the safety net.
    """

    def __init__(
        self,
        command_bus: CommandBus,
        query_bus: QueryBus,
        service: AudioRecordingService,
    ) -> None:
        self._command_bus = command_bus
        self._query_bus = query_bus
        self._service = service
        self._lock = asyncio.Lock()
        self._active_channels: set[str] = set()

    async def handle_channel_recording_started(
        self, event: ChannelRecordingStartedEvent
    ) -> None:
        """First channel start → start audio recording."""
        async with self._lock:
            self._active_channels.add(event.channel_name)

            if self._service.is_recording:
                logger.debug(
                    "Audio already recording — ignoring start for channel %s",
                    event.channel_name,
                )
                return

            # Fetch filename prefix from Justin API via QueryBus
            filename_prefix = await self._get_filename_prefix(event.channel_name)

            session_id = str(uuid.uuid4())
            result = await self._command_bus.execute(
                StartAudioRecordingCommand(
                    filename_prefix=filename_prefix,
                    session_id=session_id,
                )
            )

            if result.get("success"):
                logger.info(
                    "Audio recording started (session=%s, trigger=%s)",
                    session_id,
                    event.channel_name,
                )
            else:
                logger.warning(
                    "Audio recording start failed: %s", result.get("message")
                )

    async def handle_channel_recording_stopped(
        self, event: ChannelRecordingStoppedEvent
    ) -> None:
        """When all channels have stopped → stop audio recording."""
        async with self._lock:
            self._active_channels.discard(event.channel_name)

            if self._active_channels:
                logger.debug(
                    "Channel %s stopped, but %d channel(s) still active",
                    event.channel_name,
                    len(self._active_channels),
                )
                return

            if not self._service.is_recording:
                return

            logger.info("All channels stopped — stopping audio recording")
            await self._command_bus.execute(StopAudioRecordingCommand())
            self._service.reset_recovery_counter()

    async def handle_auto_stop_triggered(
        self, event: AutoStopTriggeredEvent
    ) -> None:
        """Auto-stop safety net — stop audio immediately."""
        async with self._lock:
            if not self._service.is_recording:
                return
            logger.warning(
                "AUTO-STOP triggered (channel=%s, %ds) — stopping audio",
                event.channel_name,
                event.recording_seconds,
            )
            await self._command_bus.execute(StopAudioRecordingCommand())
            self._active_channels.clear()

    async def handle_device_disconnected(
        self, event: AudioDeviceDisconnectedEvent
    ) -> None:
        """Device lost — recording already stopped by watchdog.

        Clean up state so next Justin start can attempt recovery.
        """
        async with self._lock:
            logger.error(
                "Audio device disconnected: %s — clearing active channels",
                event.device_name,
            )
            self._active_channels.clear()

    async def _get_filename_prefix(self, channel_name: str) -> str:
        """Get filename prefix from Justin API, with local fallback."""
        try:
            prefix = await self._query_bus.execute(
                GetCurrentFilenameQuery(channel=channel_name)
            )
            if prefix:
                return prefix
        except Exception:
            logger.warning(
                "Could not get filename from Justin — using local timestamp",
                exc_info=True,
            )

        return datetime.now().strftime("%y%m%d_%H%M_%S")
