"""
Audio Recording Domain Registration

Wires commands, queries, and event subscriptions into the CQRS infrastructure.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.cqrs.command_bus import CommandBus
from app.core.cqrs.query_bus import QueryBus
from app.core.events.audio_events import AudioDeviceDisconnectedEvent
from app.core.events.event_bus import DomainEventBus
from app.core.events.ingest_events import (
    AutoStopTriggeredEvent,
    ChannelRecordingStartedEvent,
    ChannelRecordingStoppedEvent,
)

from .command_handlers import (
    StartAudioRecordingCommandHandler,
    StopAudioRecordingCommandHandler,
)
from .commands import StartAudioRecordingCommand, StopAudioRecordingCommand
from .event_handlers import AudioRecordingEventHandler
from .queries import (
    GetAudioDevicesQuery,
    GetAudioRecordingStatusQuery,
    GetAudioTrackConfigQuery,
)
from .query_handlers import (
    GetAudioDevicesQueryHandler,
    GetAudioRecordingStatusQueryHandler,
    GetAudioTrackConfigQueryHandler,
)
from .service import AudioRecordingService


async def register_audio_recording_domain(
    command_bus: CommandBus,
    query_bus: QueryBus,
    event_bus: DomainEventBus,
    service: AudioRecordingService,
    get_user_setting: Callable[[str], Awaitable[Any]],
) -> None:
    """Register all audio recording domain components.

    Args:
        command_bus: The command bus for command handlers.
        query_bus: The query bus for query handlers.
        event_bus: The event bus for event subscriptions.
        service: The AudioRecordingService singleton.
        get_user_setting: Async callable ``(key: str) -> Any`` for reading user settings.
    """
    logging.info("Registering 'AudioRecording' domain handlers...")

    # ── Command handlers ───────────────────────────────────────
    start_handler = StartAudioRecordingCommandHandler(service, get_user_setting)
    command_bus.register(StartAudioRecordingCommand, start_handler.handle)

    stop_handler = StopAudioRecordingCommandHandler(service)
    command_bus.register(StopAudioRecordingCommand, stop_handler.handle)

    # ── Query handlers ─────────────────────────────────────────
    devices_handler = GetAudioDevicesQueryHandler(service)
    query_bus.register(GetAudioDevicesQuery, devices_handler.handle)

    status_handler = GetAudioRecordingStatusQueryHandler(service)
    query_bus.register(GetAudioRecordingStatusQuery, status_handler.handle)

    track_config_handler = GetAudioTrackConfigQueryHandler(get_user_setting)
    query_bus.register(GetAudioTrackConfigQuery, track_config_handler.handle)

    # ── Event subscriptions (slavet til Justin) ────────────────
    event_handler = AudioRecordingEventHandler(
        command_bus, query_bus, service, get_user_setting
    )

    await event_bus.subscribe(
        ChannelRecordingStartedEvent,
        event_handler.handle_channel_recording_started,
    )
    await event_bus.subscribe(
        ChannelRecordingStoppedEvent,
        event_handler.handle_channel_recording_stopped,
    )
    await event_bus.subscribe(
        AutoStopTriggeredEvent,
        event_handler.handle_auto_stop_triggered,
    )
    await event_bus.subscribe(
        AudioDeviceDisconnectedEvent,
        event_handler.handle_device_disconnected,
    )

    logging.info("AudioRecording domain registration completed")
