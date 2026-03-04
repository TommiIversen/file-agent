"""
Tests for the Auto-Stop Recording Feature

Covers:
- StateService auto-stop detection logic (threshold crossing, warnings, guard flags)
- AutoStopHandler action execution
- Disabled mode (limit=0)
- Guard flag reset when recording stops
- get_auto_stop_info() output
- IngestStatusUpdatedEvent includes auto_stop_info
"""
import asyncio
from typing import List
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.events.event_bus import DomainEventBus
from app.domains.ingest_monitor.events import (
    AutoStopWarningEvent,
    AutoStopTriggeredEvent,
    IngestStatusUpdatedEvent,
)
from app.domains.ingest_monitor.state_service import IngestStateService
from app.domains.ingest_monitor.auto_stop_handler import AutoStopHandler
from app.domains.ingest_monitor.models import JustInRecordingStatus, JustInOptions


# ── Helpers ───────────────────────────────────────────────────────────

def _make_status(channel: str, *, rec: bool, hours: int = 0, minutes: int = 0, seconds: int = 0):
    """Create a JustInRecordingStatus with given timecodes."""
    return (
        channel,
        JustInRecordingStatus(
            rec=rec,
            channel=channel,
            name=channel,
            hours=hours,
            minutes=minutes,
            seconds=seconds,
            options=JustInOptions(TOAJustInEngineVideoSignalAvailable=True),
        ),
    )


class EventCollector:
    """Collects events published to the event bus for assertions."""

    def __init__(self):
        self.warnings: List[AutoStopWarningEvent] = []
        self.triggers: List[AutoStopTriggeredEvent] = []
        self.status_updates: List[IngestStatusUpdatedEvent] = []

    async def on_warning(self, event: AutoStopWarningEvent):
        self.warnings.append(event)

    async def on_triggered(self, event: AutoStopTriggeredEvent):
        self.triggers.append(event)

    async def on_status(self, event: IngestStatusUpdatedEvent):
        self.status_updates.append(event)


async def _setup(
    auto_stop_minutes: int = 3,
    auto_stop_warning_minutes: int = 1,
) -> tuple[IngestStateService, DomainEventBus, EventCollector]:
    """Create a wired-up StateService + EventCollector."""
    bus = DomainEventBus()
    collector = EventCollector()
    await bus.subscribe(AutoStopWarningEvent, collector.on_warning)
    await bus.subscribe(AutoStopTriggeredEvent, collector.on_triggered)
    await bus.subscribe(IngestStatusUpdatedEvent, collector.on_status)

    svc = IngestStateService(
        event_bus=bus,
        auto_stop_minutes=auto_stop_minutes,
        auto_stop_warning_minutes=auto_stop_warning_minutes,
    )
    svc.add_new_channels(["KAM_1", "KAM_2"])
    return svc, bus, collector


# ── Tests: Disabled mode ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_auto_stop_disabled_when_limit_zero():
    """When auto_stop_minutes=0, no warning or trigger events are published."""
    svc, _, collector = await _setup(auto_stop_minutes=0)

    # Recording for 99 hours should not trigger anything
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, hours=99),
    ])

    assert len(collector.warnings) == 0
    assert len(collector.triggers) == 0


@pytest.mark.asyncio
async def test_get_auto_stop_info_disabled():
    """get_auto_stop_info reports enabled=False when limit is 0."""
    svc, _, _ = await _setup(auto_stop_minutes=0)
    info = svc.get_auto_stop_info()
    assert info["enabled"] is False
    assert info["limit_seconds"] == 0


# ── Tests: Warning detection ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_warning_event_published_at_threshold():
    """Warning fires when recording reaches (limit - warning) threshold."""
    # 3 min limit, 1 min warning => warning at 120s
    svc, _, collector = await _setup(auto_stop_minutes=3, auto_stop_warning_minutes=1)

    # Below threshold: 1m59s recording — no warning
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, minutes=1, seconds=59),
        _make_status("KAM_2", rec=True, minutes=0, seconds=30),
    ])
    assert len(collector.warnings) == 0

    # At threshold: 2m00s recording — warning fires
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, minutes=2, seconds=0),
        _make_status("KAM_2", rec=True, minutes=0, seconds=30),
    ])
    assert len(collector.warnings) == 1
    evt = collector.warnings[0]
    assert evt.channel_name == "KAM_1"
    assert evt.recording_seconds == 120
    assert evt.remaining_seconds == 60


@pytest.mark.asyncio
async def test_warning_only_sent_once():
    """Guard flag prevents repeated warning events."""
    svc, _, collector = await _setup(auto_stop_minutes=3, auto_stop_warning_minutes=1)

    # Cross warning threshold
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, minutes=2, seconds=10),
    ])
    assert len(collector.warnings) == 1

    # Next poll — still past warning, should NOT fire again
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, minutes=2, seconds=12),
    ])
    assert len(collector.warnings) == 1  # Still just one


# ── Tests: Trigger detection ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_trigger_event_published_at_limit():
    """Trigger fires when recording reaches the configured limit."""
    svc, _, collector = await _setup(auto_stop_minutes=3, auto_stop_warning_minutes=1)

    # Just under the limit
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, minutes=2, seconds=59),
    ])
    assert len(collector.triggers) == 0

    # At the limit
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, minutes=3, seconds=0),
    ])
    assert len(collector.triggers) == 1
    evt = collector.triggers[0]
    assert evt.channel_name == "KAM_1"
    assert evt.recording_seconds == 180
    assert evt.limit_seconds == 180


@pytest.mark.asyncio
async def test_trigger_only_sent_once():
    """Guard flag prevents repeated trigger events."""
    svc, _, collector = await _setup(auto_stop_minutes=3, auto_stop_warning_minutes=1)

    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, minutes=3, seconds=5),
    ])
    assert len(collector.triggers) == 1

    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, minutes=3, seconds=7),
    ])
    assert len(collector.triggers) == 1  # Still one


@pytest.mark.asyncio
async def test_trigger_uses_longest_recording_channel():
    """The channel with the longest recording time triggers the event."""
    svc, _, collector = await _setup(auto_stop_minutes=3, auto_stop_warning_minutes=1)

    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, minutes=1, seconds=0),
        _make_status("KAM_2", rec=True, minutes=3, seconds=0),
    ])
    assert len(collector.triggers) == 1
    assert collector.triggers[0].channel_name == "KAM_2"


# ── Tests: Guard flag reset ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_guards_reset_when_recording_stops():
    """When all channels stop recording, guard flags reset — next session can trigger again."""
    svc, _, collector = await _setup(auto_stop_minutes=3, auto_stop_warning_minutes=1)

    # Trigger auto-stop
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, minutes=3, seconds=0),
    ])
    assert len(collector.triggers) == 1

    # All channels stop
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=False),
        _make_status("KAM_2", rec=False),
    ])

    # New recording session — should be able to trigger again
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, minutes=3, seconds=1),
    ])
    assert len(collector.triggers) == 2


# ── Tests: get_auto_stop_info() ──────────────────────────────────────

@pytest.mark.asyncio
async def test_get_auto_stop_info_running():
    """get_auto_stop_info reflects current state when recording."""
    svc, _, _ = await _setup(auto_stop_minutes=3, auto_stop_warning_minutes=1)

    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, minutes=1, seconds=30),
    ])

    info = svc.get_auto_stop_info()
    assert info["enabled"] is True
    assert info["limit_seconds"] == 180
    assert info["max_recording_seconds"] == 90
    assert info["remaining_seconds"] == 90
    assert info["warning_sent"] is False
    assert info["triggered"] is False


@pytest.mark.asyncio
async def test_get_auto_stop_info_after_warning():
    """get_auto_stop_info shows warning_sent=True after warning fires."""
    svc, _, _ = await _setup(auto_stop_minutes=3, auto_stop_warning_minutes=1)

    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, minutes=2, seconds=30),
    ])

    info = svc.get_auto_stop_info()
    assert info["warning_sent"] is True
    assert info["triggered"] is False
    assert info["remaining_seconds"] == 30


# ── Tests: IngestStatusUpdatedEvent contains auto_stop_info ──────────

@pytest.mark.asyncio
async def test_status_event_includes_auto_stop_info():
    """IngestStatusUpdatedEvent includes auto_stop_info dict."""
    svc, _, collector = await _setup(auto_stop_minutes=3, auto_stop_warning_minutes=1)

    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, minutes=1),
    ])

    assert len(collector.status_updates) >= 1
    last_event = collector.status_updates[-1]
    assert "enabled" in last_event.auto_stop_info
    assert last_event.auto_stop_info["enabled"] is True
    assert last_event.auto_stop_info["limit_seconds"] == 180


# ── Tests: AutoStopHandler ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_auto_stop_handler_stops_all_channels():
    """AutoStopHandler calls stop on every active channel."""
    mock_client = AsyncMock()
    mock_client.get_active_channels = AsyncMock(return_value=["KAM_1", "KAM_2", "KAM_3"])
    mock_client.stop_channel = AsyncMock(return_value=True)

    handler = AutoStopHandler(api_client=mock_client)

    event = AutoStopTriggeredEvent(
        channel_name="KAM_2",
        recording_seconds=180,
        limit_seconds=180,
    )
    await handler.handle_auto_stop_triggered(event)

    mock_client.get_active_channels.assert_awaited_once()
    assert mock_client.stop_channel.await_count == 3
    mock_client.stop_channel.assert_any_await("KAM_1")
    mock_client.stop_channel.assert_any_await("KAM_2")
    mock_client.stop_channel.assert_any_await("KAM_3")


@pytest.mark.asyncio
async def test_auto_stop_handler_handles_no_channels():
    """AutoStopHandler exits gracefully if no active channels found."""
    mock_client = AsyncMock()
    mock_client.get_active_channels = AsyncMock(return_value=None)

    handler = AutoStopHandler(api_client=mock_client)
    event = AutoStopTriggeredEvent(
        channel_name="KAM_1",
        recording_seconds=180,
        limit_seconds=180,
    )
    # Should not raise
    await handler.handle_auto_stop_triggered(event)
    mock_client.stop_channel.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_stop_handler_handles_partial_failure():
    """AutoStopHandler logs but continues if some channels fail to stop."""
    mock_client = AsyncMock()
    mock_client.get_active_channels = AsyncMock(return_value=["KAM_1", "KAM_2"])
    mock_client.stop_channel = AsyncMock(side_effect=[False, True])

    handler = AutoStopHandler(api_client=mock_client)
    event = AutoStopTriggeredEvent(
        channel_name="KAM_1",
        recording_seconds=180,
        limit_seconds=180,
    )
    await handler.handle_auto_stop_triggered(event)
    assert mock_client.stop_channel.await_count == 2


# ── Tests: Edge cases ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_events_when_no_channels_recording():
    """Even with auto-stop enabled, no events when nobody is recording."""
    svc, _, collector = await _setup(auto_stop_minutes=3, auto_stop_warning_minutes=1)

    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=False),
        _make_status("KAM_2", rec=False),
    ])

    assert len(collector.warnings) == 0
    assert len(collector.triggers) == 0


@pytest.mark.asyncio
async def test_warning_skip_when_warning_minutes_exceeds_limit():
    """If warning_minutes >= limit_minutes, warning_seconds=0 so no warning fires."""
    svc, _, collector = await _setup(auto_stop_minutes=3, auto_stop_warning_minutes=5)

    # Recording 2 minutes — past what would be the warning, but warning_seconds=0
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, minutes=2, seconds=30),
    ])
    assert len(collector.warnings) == 0

    # Trigger still fires at limit
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, minutes=3),
    ])
    assert len(collector.triggers) == 1
    # Warning was skipped but trigger set warning_sent=True as well
    assert svc._auto_stop_warning_sent is True
