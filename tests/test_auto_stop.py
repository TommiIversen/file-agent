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

def _make_status(
    channel: str,
    *,
    rec: bool,
    hours: int = 0,
    minutes: int = 0,
    seconds: int = 0,
    frames: int = 0,
    start_frames: int = 0,
    framerate: int = 2500,
):
    """Create a JustInRecordingStatus with given timecodes.

    With ``start_frames=0`` (default) the timecode fields directly represent
    the recording *duration*, which keeps existing test values unchanged.
    """
    return (
        channel,
        JustInRecordingStatus(
            rec=rec,
            channel=channel,
            name=channel,
            hours=hours,
            minutes=minutes,
            seconds=seconds,
            frames=frames,
            options=JustInOptions(
                TOAJustInEngineVideoSignalAvailable=True,
                TOAJustInEngineStartTimecodeFrames=start_frames,
                TOAJustInEngineFramerate=framerate,
            ),
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


# ── Tests: Real-world timecode scenarios ─────────────────────────────

@pytest.mark.asyncio
async def test_wall_clock_timecode_not_treated_as_duration():
    """Realistic scenario: timecode is 12:46:30 but recording only 3 min.

    This is the bug the user reported — old code treated wall-clock TC as
    duration, causing immediate auto-stop.
    """
    svc, _, collector = await _setup(auto_stop_minutes=4, auto_stop_warning_minutes=1)

    # start_timecode_frames = 12:43:27 * 25fps = 1145175
    start_frames = (12 * 3600 + 43 * 60 + 27) * 25  # 1145175

    # Current timecode 12:46:30 → ~3 min of recording → under 4 min limit
    await svc.update_channel_statuses([
        _make_status(
            "KAM_1",
            rec=True,
            hours=12,
            minutes=46,
            seconds=30,
            start_frames=start_frames,
            framerate=2500,
        ),
    ])
    # Should NOT trigger (only ~3 min of actual recording)
    assert len(collector.triggers) == 0
    assert len(collector.warnings) == 1  # 3 min ≥ warning threshold (4-1=3)

    # 12:47:27 → 4 minutes of recording → trigger
    await svc.update_channel_statuses([
        _make_status(
            "KAM_1",
            rec=True,
            hours=12,
            minutes=47,
            seconds=27,
            start_frames=start_frames,
            framerate=2500,
        ),
    ])
    assert len(collector.triggers) == 1


@pytest.mark.asyncio
async def test_midnight_wraparound():
    """Recording starts at 23:58:00, current timecode is 00:02:00 → 4 min duration."""
    svc, _, collector = await _setup(auto_stop_minutes=5, auto_stop_warning_minutes=1)

    start_frames = (23 * 3600 + 58 * 60 + 0) * 25  # 23:58:00 in frames

    # 00:02:00 next day → 4 minutes of recording
    await svc.update_channel_statuses([
        _make_status(
            "KAM_1",
            rec=True,
            hours=0,
            minutes=2,
            seconds=0,
            start_frames=start_frames,
            framerate=2500,
        ),
    ])
    assert len(collector.triggers) == 0  # 4 min < 5 min limit
    assert len(collector.warnings) == 1  # 4 min ≥ warning threshold (5-1=4)


@pytest.mark.asyncio
async def test_missing_start_frames_returns_zero_duration():
    """If start_timecode_frames is None, duration is 0 (auto-stop won't fire)."""
    svc, _, collector = await _setup(auto_stop_minutes=1, auto_stop_warning_minutes=0)

    await svc.update_channel_statuses([
        (
            "KAM_1",
            JustInRecordingStatus(
                rec=True,
                channel="KAM_1",
                name="KAM_1",
                hours=12,
                minutes=40,
                seconds=0,
                options=JustInOptions(
                    TOAJustInEngineVideoSignalAvailable=True,
                    TOAJustInEngineStartTimecodeFrames=None,
                    TOAJustInEngineFramerate=2500,
                ),
            ),
        ),
    ])
    # Should not trigger — we can't calculate duration
    assert len(collector.triggers) == 0
