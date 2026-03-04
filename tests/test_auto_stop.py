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


def _tc_to_frames(h: int, m: int, s: int, fps: int = 25) -> int:
    """Convert h:m:s to total frames at given fps."""
    return (h * 3600 + m * 60 + s) * fps


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
    """Create a raw JustInRecordingStatus with explicit timecodes.

    For recording statuses with proper wall-clock TCs, prefer ``_make_recording``.
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


def _make_recording(
    channel: str,
    *,
    duration_sec: int,
    start_hour: int = 10,
    start_min: int = 0,
    framerate: int = 2500,
):
    """Create a rec=True status with realistic wall-clock timecodes.

    ``start_hour:start_min`` is when the recording started (converted to
    StartTimecodeFrames).  The current TC is ``start + duration_sec``.
    """
    start_frames = _tc_to_frames(start_hour, start_min, 0, framerate // 100)
    total_start_sec = start_hour * 3600 + start_min * 60
    current_sec = total_start_sec + duration_sec
    h = current_sec // 3600
    m = (current_sec % 3600) // 60
    s = current_sec % 60
    return _make_status(
        channel, rec=True, hours=h, minutes=m, seconds=s,
        start_frames=start_frames, framerate=framerate,
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
        _make_recording("KAM_1", duration_sec=119),
        _make_recording("KAM_2", duration_sec=30),
    ])
    assert len(collector.warnings) == 0

    # At threshold: 2m00s recording — warning fires
    await svc.update_channel_statuses([
        _make_recording("KAM_1", duration_sec=120),
        _make_recording("KAM_2", duration_sec=30),
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
        _make_recording("KAM_1", duration_sec=130),
    ])
    assert len(collector.warnings) == 1

    # Next poll — still past warning, should NOT fire again
    await svc.update_channel_statuses([
        _make_recording("KAM_1", duration_sec=132),
    ])
    assert len(collector.warnings) == 1  # Still just one


# ── Tests: Trigger detection ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_trigger_event_published_at_limit():
    """Trigger fires when recording reaches the configured limit."""
    svc, _, collector = await _setup(auto_stop_minutes=3, auto_stop_warning_minutes=1)

    # Just under the limit
    await svc.update_channel_statuses([
        _make_recording("KAM_1", duration_sec=179),
    ])
    assert len(collector.triggers) == 0

    # At the limit
    await svc.update_channel_statuses([
        _make_recording("KAM_1", duration_sec=180),
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
        _make_recording("KAM_1", duration_sec=185),
    ])
    assert len(collector.triggers) == 1

    await svc.update_channel_statuses([
        _make_recording("KAM_1", duration_sec=187),
    ])
    assert len(collector.triggers) == 1  # Still one


@pytest.mark.asyncio
async def test_trigger_uses_longest_recording_channel():
    """The channel with the longest recording time triggers the event."""
    svc, _, collector = await _setup(auto_stop_minutes=3, auto_stop_warning_minutes=1)

    await svc.update_channel_statuses([
        _make_recording("KAM_1", duration_sec=60),
        _make_recording("KAM_2", duration_sec=180),
    ])
    assert len(collector.triggers) == 1
    assert collector.triggers[0].channel_name == "KAM_2"


# ── Tests: Guard flag reset ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_guards_reset_when_recording_stops():
    """When all channels stop recording, guard flags reset — next session can trigger again."""
    svc, _, collector = await _setup(auto_stop_minutes=3, auto_stop_warning_minutes=1)

    # Trigger auto-stop (session 1, start TC 10:00)
    await svc.update_channel_statuses([
        _make_recording("KAM_1", duration_sec=180),
    ])
    assert len(collector.triggers) == 1

    # All channels stop
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=False),
        _make_status("KAM_2", rec=False),
    ])

    # New recording session (session 2, different start TC 10:05)
    await svc.update_channel_statuses([
        _make_recording("KAM_1", duration_sec=181, start_hour=10, start_min=5),
    ])
    assert len(collector.triggers) == 2


# ── Tests: get_auto_stop_info() ──────────────────────────────────────

@pytest.mark.asyncio
async def test_get_auto_stop_info_running():
    """get_auto_stop_info reflects current state when recording."""
    svc, _, _ = await _setup(auto_stop_minutes=3, auto_stop_warning_minutes=1)

    await svc.update_channel_statuses([
        _make_recording("KAM_1", duration_sec=90),
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
        _make_recording("KAM_1", duration_sec=150),
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
        _make_recording("KAM_1", duration_sec=60),
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

    # Recording 2.5 min — past what would be the warning, but warning_seconds=0
    await svc.update_channel_statuses([
        _make_recording("KAM_1", duration_sec=150),
    ])
    assert len(collector.warnings) == 0

    # Trigger still fires at limit
    await svc.update_channel_statuses([
        _make_recording("KAM_1", duration_sec=180),
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


# ── Tests: Multi-session lifecycle (the "immediate stop" bug) ────────


@pytest.mark.asyncio
async def test_second_session_not_immediately_stopped():
    """After auto-stop and reset, a new recording with fresh timecodes must NOT trigger immediately.

    This reproduces the real-world bug:
    1. Session 1 records for 4 min → auto-stop
    2. Channels stop, guards reset
    3. Session 2 starts (fresh start_timecode_frames) → should be ~0 seconds
    """
    svc, _, collector = await _setup(auto_stop_minutes=4, auto_stop_warning_minutes=1)

    # ── Session 1: recording starts at TC 10:00:00 ──
    start1 = _tc_to_frames(10, 0, 0)

    # 2 min in → warning should not fire yet
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, hours=10, minutes=2, seconds=0, start_frames=start1),
        _make_status("KAM_2", rec=True, hours=10, minutes=2, seconds=0, start_frames=start1),
    ])
    assert len(collector.warnings) == 0
    assert len(collector.triggers) == 0

    # 3 min in → warning fires (4-1=3 min threshold)
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, hours=10, minutes=3, seconds=0, start_frames=start1),
        _make_status("KAM_2", rec=True, hours=10, minutes=3, seconds=0, start_frames=start1),
    ])
    assert len(collector.warnings) == 1

    # 4 min in → trigger fires
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, hours=10, minutes=4, seconds=0, start_frames=start1),
        _make_status("KAM_2", rec=True, hours=10, minutes=4, seconds=0, start_frames=start1),
    ])
    assert len(collector.triggers) == 1

    # ── Stop issued by AutoStopHandler — next poll still rec=true briefly ──
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, hours=10, minutes=4, seconds=3, start_frames=start1),
        _make_status("KAM_2", rec=True, hours=10, minutes=4, seconds=3, start_frames=start1),
    ])
    # No duplicate trigger
    assert len(collector.triggers) == 1

    # ── Channels finally stop ──
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=False, hours=0, minutes=0, seconds=0, start_frames=0),
        _make_status("KAM_2", rec=False, hours=0, minutes=0, seconds=0, start_frames=0),
    ])
    # Guards should be reset
    assert svc._auto_stop_triggered is False
    assert svc._auto_stop_warning_sent is False

    # ── Session 2: new recording starts at TC 10:06:00 ──
    start2 = _tc_to_frames(10, 6, 0)

    # Just started — ~0 seconds of recording
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, hours=10, minutes=6, seconds=3, start_frames=start2),
        _make_status("KAM_2", rec=True, hours=10, minutes=6, seconds=3, start_frames=start2),
    ])
    # MUST NOT trigger immediately — only 3 seconds of recording
    assert len(collector.triggers) == 1  # Still just the one from session 1
    assert len(collector.warnings) == 1  # Still just the one from session 1

    # Session 2: 1 min in
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, hours=10, minutes=7, seconds=0, start_frames=start2),
    ])
    assert len(collector.triggers) == 1  # Still no new trigger

    # Session 2: 3 min in → warning fires for session 2
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, hours=10, minutes=9, seconds=0, start_frames=start2),
    ])
    assert len(collector.warnings) == 2  # Session 2 warning

    # Session 2: 4 min in → trigger fires for session 2
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, hours=10, minutes=10, seconds=0, start_frames=start2),
    ])
    assert len(collector.triggers) == 2  # Session 2 trigger


@pytest.mark.asyncio
async def test_three_sequential_sessions():
    """Three full recording sessions → each should trigger independently."""
    svc, _, collector = await _setup(auto_stop_minutes=2, auto_stop_warning_minutes=0)

    for session_idx in range(3):
        start_min = session_idx * 5  # Each session starts 5 min apart
        start_frames = _tc_to_frames(14, start_min, 0)

        # Record for 2 min → trigger
        await svc.update_channel_statuses([
            _make_status(
                "KAM_1", rec=True,
                hours=14, minutes=start_min + 2, seconds=0,
                start_frames=start_frames,
            ),
        ])
        assert len(collector.triggers) == session_idx + 1, (
            f"Session {session_idx + 1}: expected {session_idx + 1} triggers, got {len(collector.triggers)}"
        )

        # Stop
        await svc.update_channel_statuses([
            _make_status("KAM_1", rec=False, start_frames=0),
        ])
        assert svc._auto_stop_triggered is False


@pytest.mark.asyncio
async def test_no_trigger_when_fresh_session_starts():
    """Even if wall-clock TC is large (e.g., 18 hours), a fresh session has 0 duration."""
    svc, _, collector = await _setup(auto_stop_minutes=1, auto_stop_warning_minutes=0)

    # Recording starts at TC 18:30:00 — a large wall-clock value
    start_frames = _tc_to_frames(18, 30, 0)

    # First poll: 5 seconds into the recording
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, hours=18, minutes=30, seconds=5, start_frames=start_frames),
    ])
    assert len(collector.triggers) == 0  # 5 sec < 1 min limit

    # 30 sec in
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, hours=18, minutes=30, seconds=30, start_frames=start_frames),
    ])
    assert len(collector.triggers) == 0

    # 1 min in → trigger
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, hours=18, minutes=31, seconds=0, start_frames=start_frames),
    ])
    assert len(collector.triggers) == 1


@pytest.mark.asyncio
async def test_guards_not_reset_while_any_channel_still_recording():
    """Guards stay set as long as at least one channel is still recording."""
    svc, _, collector = await _setup(auto_stop_minutes=2, auto_stop_warning_minutes=0)

    start = _tc_to_frames(9, 0, 0)

    # Both channels recording, hit limit
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, hours=9, minutes=2, seconds=0, start_frames=start),
        _make_status("KAM_2", rec=True, hours=9, minutes=2, seconds=0, start_frames=start),
    ])
    assert len(collector.triggers) == 1
    assert svc._auto_stop_triggered is True

    # KAM_1 stops, but KAM_2 still recording — guards must NOT reset
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=False, start_frames=0),
        _make_status("KAM_2", rec=True, hours=9, minutes=2, seconds=5, start_frames=start),
    ])
    assert svc._auto_stop_triggered is True  # Guard still set — KAM_2 still recording
    assert len(collector.triggers) == 1  # No duplicate trigger

    # Now KAM_2 also stops — guards reset
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=False, start_frames=0),
        _make_status("KAM_2", rec=False, start_frames=0),
    ])
    assert svc._auto_stop_triggered is False
    assert svc._auto_stop_warning_sent is False


@pytest.mark.asyncio
async def test_stale_start_frames_zero_from_idle_does_not_cause_false_trigger():
    """When rec=false, Justin reports start_frames=0. This idle data must not
    leak into the next session's first `rec=true` poll."""
    svc, _, collector = await _setup(auto_stop_minutes=2, auto_stop_warning_minutes=0)

    # Channel idle: rec=false, start_frames=0 (standard Justin idle response)
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=False, hours=0, minutes=24, seconds=47, start_frames=0),
    ])
    assert len(collector.triggers) == 0

    # New recording starts — Justin provides fresh start_frames
    new_start = _tc_to_frames(14, 0, 0)
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, hours=14, minutes=0, seconds=5, start_frames=new_start),
    ])
    # 5 seconds of recording — nowhere near the limit
    assert len(collector.triggers) == 0


@pytest.mark.asyncio
async def test_auto_stop_info_reflects_correct_duration_with_wall_clock():
    """get_auto_stop_info must report actual *recording* duration, not wall-clock TC."""
    svc, _, _ = await _setup(auto_stop_minutes=10, auto_stop_warning_minutes=2)

    start = _tc_to_frames(15, 30, 0)

    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, hours=15, minutes=33, seconds=0, start_frames=start),
    ])

    info = svc.get_auto_stop_info()
    assert info["max_recording_seconds"] == 180  # 3 min of actual recording
    assert info["remaining_seconds"] == 600 - 180  # 10 min limit - 3 min = 7 min


# ── Tests: start_frames=0 regression (the "second run" bug) ─────────

@pytest.mark.asyncio
async def test_zero_start_frames_with_rec_true_returns_zero_duration():
    """If Justin reports StartTimecodeFrames=0 for rec=true, duration must be 0.

    This is the root cause of the "second run" bug:
    After auto-stop, Justin may report rec=true with StartTimecodeFrames=0
    (its idle value), causing the old code to interpret the full wall-clock TC
    (e.g. 14:05:00 = 50700s) as recording duration → instant trigger.
    """
    svc, _, collector = await _setup(auto_stop_minutes=1, auto_stop_warning_minutes=0)

    # rec=true but start_frames=0 (Justin idle marker leaked into recording state)
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, hours=14, minutes=5, seconds=0, start_frames=0),
    ])
    # Must NOT trigger — start_frames=0 means "no start data" → duration=0
    assert len(collector.triggers) == 0
    assert len(collector.warnings) == 0

    # Once Justin provides proper start_frames, duration works normally
    proper_start = _tc_to_frames(14, 5, 0)
    await svc.update_channel_statuses([
        _make_status("KAM_1", rec=True, hours=14, minutes=6, seconds=5,
                     start_frames=proper_start),
    ])
    # 65 seconds of recording ≥ 60s limit → trigger
    assert len(collector.triggers) == 1