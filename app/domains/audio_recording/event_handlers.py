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
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Optional, Tuple

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
        get_user_setting: Callable[[str], Awaitable[Any]],
    ) -> None:
        self._command_bus = command_bus
        self._query_bus = query_bus
        self._service = service
        self._get_user_setting = get_user_setting
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

            # Fetch filename stem from Justin API via QueryBus
            filename_stem, channel_name = await self._get_filename_stem(
                event.channel_name
            )

            session_id = str(uuid.uuid4())
            result = await self._command_bus.execute(
                StartAudioRecordingCommand(
                    filename_stem=filename_stem,
                    channel_name=channel_name,
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

    async def _get_filename_stem(
        self, channel_name: str
    ) -> Tuple[str, Optional[str]]:
        """Get filename stem from Justin API, with retry + local fallback.

        Justin may not have the filename ready immediately after recording
        starts.  We retry a few times with a short delay before falling back
        to a local timestamp.

        Returns:
            ``(stem, channel_name)`` when Justin API succeeds — e.g.
            ``("260414_151304_KAM_1", "KAM_1")``.
            ``(local_timestamp, None)`` on fallback — e.g.
            ``("260414_151304", None)``.
        """
        # Check if Justin naming is enabled
        use_justin = await self._get_user_setting("audio_filename_from_justin")
        if not use_justin:
            logger.info("Justin filename disabled — using local timestamp")
            return datetime.now().strftime("%y%m%d_%H%M%S"), None

        max_retries = 3
        retry_delay = 2.0  # seconds

        for attempt in range(max_retries):
            try:
                stem = await self._query_bus.execute(
                    GetCurrentFilenameQuery(channel=channel_name)
                )
                if stem:
                    return stem, channel_name
            except Exception:
                logger.warning(
                    "Could not get filename from Justin (attempt %d/%d)",
                    attempt + 1,
                    max_retries,
                    exc_info=True,
                )

            if attempt < max_retries - 1:
                logger.debug(
                    "Filename not ready yet — retrying in %.1fs (attempt %d/%d)",
                    retry_delay,
                    attempt + 1,
                    max_retries,
                )
                await asyncio.sleep(retry_delay)

        logger.warning("All filename retries exhausted — using local timestamp")
        return datetime.now().strftime("%y%m%d_%H%M%S"), None
