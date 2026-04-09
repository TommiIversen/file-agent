"""
Tests for IngestStateService — the untested parts:
- _channel_recording_seconds (timecode math with edge cases)
- _check_auto_stop (warning/trigger/guard logic)
- update_channel_errors (error change detection)
- clear_all_errors
- update_recording_paths / get_recording_paths
- update_active_channels (remove inactive)
- set_connection_status
"""
import pytest
from unittest.mock import AsyncMock

from app.core.events.event_bus import DomainEventBus
from app.domains.ingest_monitor.state_service import IngestStateService
from app.domains.ingest_monitor.models import ChannelState, JustInRecordingStatus, JustInOptions, JustInError, JustInErrorInfo
from app.domains.ingest_monitor.events import (
    AutoStopWarningEvent,
    AutoStopTriggeredEvent,
    ChannelErrorDetectedEvent,
    IngestOnlineEvent,
    IngestOfflineEvent,
    IngestStatusUpdatedEvent,
    RecordingPathsDiscoveredEvent,
)


def _make_channel(
    name: str = "KAM_1",
    is_recording: bool = False,
    hours: int = 0,
    minutes: int = 0,
    seconds: int = 0,
    frames: int = 0,
    start_timecode_frames: int = 0,
    framerate: int = 2500,  # 25 fps
    has_signal: bool = True,
) -> ChannelState:
    return ChannelState(
        name=name,
        is_recording=is_recording,
        has_signal=has_signal,
        hours=hours,
        minutes=minutes,
        seconds=seconds,
        frames=frames,
        start_timecode_frames=start_timecode_frames,
        framerate=framerate,
    )


def _make_recording_status(
    channel: str = "KAM_1",
    rec: bool = True,
    hours: int = 0,
    minutes: int = 0,
    seconds: int = 0,
    frames: int = 0,
    start_frames: int = 0,
    framerate: int = 2500,
    signal: bool = True,
) -> JustInRecordingStatus:
    return JustInRecordingStatus(
        rec=rec,
        channel=channel,
        name=channel,
        hours=hours,
        minutes=minutes,
        seconds=seconds,
        frames=frames,
        options=JustInOptions(
            TOAJustInEngineVideoSignalAvailable=signal,
            TOAJustInEngineStartTimecodeFrames=start_frames,
            TOAJustInEngineFramerate=framerate,
        ),
    )


class _EventCollector:
    """Collects published events for assertions."""

    def __init__(self):
        self.events = []

    async def handler(self, event):
        self.events.append(event)

    def of_type(self, event_type):
        return [e for e in self.events if isinstance(e, event_type)]


async def _make_service(auto_stop_minutes: int = 0, auto_stop_warning_minutes: int = 5):
    event_bus = DomainEventBus()
    collector = _EventCollector()

    # Subscribe to all events we care about
    for event_type in [
        AutoStopWarningEvent, AutoStopTriggeredEvent,
        ChannelErrorDetectedEvent, IngestOnlineEvent, IngestOfflineEvent,
        IngestStatusUpdatedEvent, RecordingPathsDiscoveredEvent,
    ]:
        await event_bus.subscribe(event_type, collector.handler)

    svc = IngestStateService(
        event_bus,
        auto_stop_minutes=auto_stop_minutes,
        auto_stop_warning_minutes=auto_stop_warning_minutes,
    )
    return svc, collector


# ── _channel_recording_seconds ──────────────────────────────────────

class TestChannelRecordingSeconds:

    def test_not_recording_returns_zero(self):
        state = _make_channel(is_recording=False)
        assert IngestStateService._channel_recording_seconds(state) == 0

    def test_zero_framerate_returns_zero(self):
        state = _make_channel(is_recording=True, framerate=0)
        assert IngestStateService._channel_recording_seconds(state) == 0

    def test_negative_framerate_returns_zero(self):
        state = _make_channel(is_recording=True, framerate=-100)
        assert IngestStateService._channel_recording_seconds(state) == 0

    def test_none_framerate_returns_zero(self):
        state = _make_channel(is_recording=True, framerate=None)
        assert IngestStateService._channel_recording_seconds(state) == 0

    def test_zero_start_timecode_returns_zero(self):
        """Justin reports 0 for idle channels — should treat as unknown."""
        state = _make_channel(
            is_recording=True, framerate=2500,
            start_timecode_frames=0,
            hours=10, minutes=0, seconds=0, frames=0,
        )
        assert IngestStateService._channel_recording_seconds(state) == 0

    def test_none_start_timecode_returns_zero(self):
        state = _make_channel(
            is_recording=True, framerate=2500,
            start_timecode_frames=None,
        )
        assert IngestStateService._channel_recording_seconds(state) == 0

    def test_negative_start_timecode_returns_zero(self):
        state = _make_channel(
            is_recording=True, framerate=2500,
            start_timecode_frames=-100,
        )
        assert IngestStateService._channel_recording_seconds(state) == 0

    def test_normal_60_second_recording(self):
        """Recording started at 10:00:00, now 10:01:00 at 25fps = 60 seconds."""
        fps = 25
        start_frames = 10 * 3600 * fps  # 10:00:00 in frames
        state = _make_channel(
            is_recording=True,
            framerate=2500,
            start_timecode_frames=start_frames,
            hours=10, minutes=1, seconds=0, frames=0,
        )
        assert IngestStateService._channel_recording_seconds(state) == 60

    def test_5_minute_recording(self):
        fps = 25
        start_frames = 12 * 3600 * fps  # 12:00:00
        state = _make_channel(
            is_recording=True,
            framerate=2500,
            start_timecode_frames=start_frames,
            hours=12, minutes=5, seconds=0, frames=0,
        )
        assert IngestStateService._channel_recording_seconds(state) == 300

    def test_midnight_wraparound(self):
        """Started at 23:59:00, now 00:01:00 — should be 120 seconds, not negative."""
        fps = 25
        start_frames = (23 * 3600 + 59 * 60) * fps  # 23:59:00
        state = _make_channel(
            is_recording=True,
            framerate=2500,
            start_timecode_frames=start_frames,
            hours=0, minutes=1, seconds=0, frames=0,
        )
        result = IngestStateService._channel_recording_seconds(state)
        assert result == 120

    def test_50fps_recording(self):
        """Test with 50fps (framerate=5000)."""
        fps = 50
        start_frames = 1 * 3600 * fps  # 01:00:00
        state = _make_channel(
            is_recording=True,
            framerate=5000,
            start_timecode_frames=start_frames,
            hours=1, minutes=0, seconds=30, frames=0,
        )
        assert IngestStateService._channel_recording_seconds(state) == 30

    def test_partial_frames_truncated(self):
        """Frames contribution should be included in duration."""
        fps = 25
        start_frames = 0 * fps + 1  # just 1 frame from start
        state = _make_channel(
            is_recording=True,
            framerate=2500,
            start_timecode_frames=start_frames,
            hours=0, minutes=0, seconds=1, frames=0,  # 1 second = 25 frames
        )
        # current = 25 frames, start = 1 frame -> 24 frames / 25 fps = 0.96s -> int = 0
        result = IngestStateService._channel_recording_seconds(state)
        assert result == 0  # truncated to int


# ── _check_auto_stop ────────────────────────────────────────────────

class TestAutoStop:

    @pytest.mark.asyncio
    async def test_auto_stop_disabled_does_nothing(self):
        svc, collector = await _make_service(auto_stop_minutes=0)
        svc.add_new_channels(["KAM_1"])
        await svc.update_channel_statuses([
            ("KAM_1", _make_recording_status(rec=True, hours=99)),
        ])
        # Only IngestStatusUpdatedEvent, no auto-stop events
        assert len(collector.of_type(AutoStopWarningEvent)) == 0
        assert len(collector.of_type(AutoStopTriggeredEvent)) == 0

    @pytest.mark.asyncio
    async def test_auto_stop_warning_published(self):
        """Warning at (limit - warning_minutes) seconds."""
        svc, collector = await _make_service(auto_stop_minutes=10, auto_stop_warning_minutes=5)
        svc.add_new_channels(["KAM_1"])

        # Recording for 6 minutes = 360s, warning threshold = (10-5)*60 = 300s
        fps = 25
        start_frames = 1 * 3600 * fps
        await svc.update_channel_statuses([
            ("KAM_1", _make_recording_status(
                rec=True, hours=1, minutes=6, seconds=0,
                start_frames=start_frames, framerate=2500,
            )),
        ])

        warnings = collector.of_type(AutoStopWarningEvent)
        assert len(warnings) == 1
        assert warnings[0].channel_name == "KAM_1"
        assert warnings[0].recording_seconds == 360

    @pytest.mark.asyncio
    async def test_auto_stop_triggered_published(self):
        svc, collector = await _make_service(auto_stop_minutes=10, auto_stop_warning_minutes=5)
        svc.add_new_channels(["KAM_1"])

        # Recording for 11 minutes = 660s, limit = 600s
        fps = 25
        start_frames = 1 * 3600 * fps
        await svc.update_channel_statuses([
            ("KAM_1", _make_recording_status(
                rec=True, hours=1, minutes=11, seconds=0,
                start_frames=start_frames, framerate=2500,
            )),
        ])

        triggers = collector.of_type(AutoStopTriggeredEvent)
        assert len(triggers) == 1
        assert triggers[0].channel_name == "KAM_1"
        assert triggers[0].recording_seconds == 660

    @pytest.mark.asyncio
    async def test_auto_stop_guard_prevents_duplicate_events(self):
        svc, collector = await _make_service(auto_stop_minutes=10, auto_stop_warning_minutes=5)
        svc.add_new_channels(["KAM_1"])

        fps = 25
        start_frames = 1 * 3600 * fps

        # First update: triggers auto-stop
        await svc.update_channel_statuses([
            ("KAM_1", _make_recording_status(
                rec=True, hours=1, minutes=11, seconds=0,
                start_frames=start_frames, framerate=2500,
            )),
        ])
        # Second update: still recording past limit
        await svc.update_channel_statuses([
            ("KAM_1", _make_recording_status(
                rec=True, hours=1, minutes=12, seconds=0,
                start_frames=start_frames, framerate=2500,
            )),
        ])

        # Should only have ONE trigger event (guard flag prevents duplicate)
        assert len(collector.of_type(AutoStopTriggeredEvent)) == 1

    @pytest.mark.asyncio
    async def test_auto_stop_guards_reset_when_all_stop_recording(self):
        svc, collector = await _make_service(auto_stop_minutes=10, auto_stop_warning_minutes=5)
        svc.add_new_channels(["KAM_1"])

        fps = 25
        start_frames = 1 * 3600 * fps

        # First: trigger auto-stop
        await svc.update_channel_statuses([
            ("KAM_1", _make_recording_status(
                rec=True, hours=1, minutes=11, seconds=0,
                start_frames=start_frames, framerate=2500,
            )),
        ])
        assert len(collector.of_type(AutoStopTriggeredEvent)) == 1

        # Stop recording
        await svc.update_channel_statuses([
            ("KAM_1", _make_recording_status(rec=False)),
        ])

        # Start recording again and exceed limit
        await svc.update_channel_statuses([
            ("KAM_1", _make_recording_status(
                rec=True, hours=2, minutes=11, seconds=0,
                start_frames=2 * 3600 * fps, framerate=2500,
            )),
        ])

        # Second trigger after guards reset
        assert len(collector.of_type(AutoStopTriggeredEvent)) == 2


# ── get_auto_stop_info ──────────────────────────────────────────────

class TestGetAutoStopInfo:

    @pytest.mark.asyncio
    async def test_disabled(self):
        svc, _ = await _make_service(auto_stop_minutes=0)
        info = svc.get_auto_stop_info()
        assert info["enabled"] is False
        assert info["limit_seconds"] == 0
        assert info["max_recording_seconds"] == 0

    @pytest.mark.asyncio
    async def test_enabled_with_recording(self):
        svc, _ = await _make_service(auto_stop_minutes=10, auto_stop_warning_minutes=5)
        svc.add_new_channels(["KAM_1"])

        fps = 25
        start_frames = 1 * 3600 * fps
        await svc.update_channel_statuses([
            ("KAM_1", _make_recording_status(
                rec=True, hours=1, minutes=3, seconds=0,
                start_frames=start_frames, framerate=2500,
            )),
        ])

        info = svc.get_auto_stop_info()
        assert info["enabled"] is True
        assert info["limit_seconds"] == 600
        assert info["max_recording_seconds"] == 180
        assert info["remaining_seconds"] == 420


# ── update_channel_errors ───────────────────────────────────────────

class TestUpdateChannelErrors:

    @pytest.mark.asyncio
    async def test_new_error_publishes_event(self):
        svc, collector = await _make_service()
        svc.add_new_channels(["KAM_1"])

        error = JustInError(
            date=1234567890.0,
            errorCode=42,
            errorUIDescription="Disk write error",
        )
        await svc.update_channel_errors([("KAM_1", [error])])

        error_events = collector.of_type(ChannelErrorDetectedEvent)
        assert len(error_events) == 1
        assert error_events[0].channel_name == "KAM_1"
        assert error_events[0].error_message == "Disk write error"
        assert error_events[0].error_code == 42

    @pytest.mark.asyncio
    async def test_same_error_does_not_republish(self):
        svc, collector = await _make_service()
        svc.add_new_channels(["KAM_1"])

        error = JustInError(date=100.0, errorCode=1, errorUIDescription="err")
        await svc.update_channel_errors([("KAM_1", [error])])
        await svc.update_channel_errors([("KAM_1", [error])])  # same date

        assert len(collector.of_type(ChannelErrorDetectedEvent)) == 1

    @pytest.mark.asyncio
    async def test_different_error_publishes_again(self):
        svc, collector = await _make_service()
        svc.add_new_channels(["KAM_1"])

        err1 = JustInError(date=100.0, errorCode=1, errorUIDescription="err1")
        err2 = JustInError(date=200.0, errorCode=2, errorUIDescription="err2")
        await svc.update_channel_errors([("KAM_1", [err1])])
        await svc.update_channel_errors([("KAM_1", [err2])])  # new date → new event

        assert len(collector.of_type(ChannelErrorDetectedEvent)) == 2

    @pytest.mark.asyncio
    async def test_unknown_channel_is_skipped(self):
        svc, collector = await _make_service()
        error = JustInError(date=100.0, errorCode=1, errorUIDescription="err")
        await svc.update_channel_errors([("UNKNOWN", [error])])
        assert len(collector.of_type(ChannelErrorDetectedEvent)) == 0

    @pytest.mark.asyncio
    async def test_error_state_updated_in_cache(self):
        svc, _ = await _make_service()
        svc.add_new_channels(["KAM_1"])

        error = JustInError(date=100.0, errorCode=1, errorUIDescription="err")
        await svc.update_channel_errors([("KAM_1", [error])])

        state = svc.get_channel_state("KAM_1")
        assert state.has_errors is True
        assert len(state.last_errors) == 1

    @pytest.mark.asyncio
    async def test_multiple_new_errors_in_batch(self):
        """Each new error in a single batch publishes its own event."""
        svc, collector = await _make_service()
        svc.add_new_channels(["KAM_1"])

        errors = [
            JustInError(date=100.0, errorCode=-8998, errorUIDescription="Dropped frames"),
            JustInError(date=200.0, errorCode=-8998, errorUIDescription="Dropped frames"),
            JustInError(date=300.0, errorCode=-8995, errorUIDescription="No signal"),
        ]
        await svc.update_channel_errors([("KAM_1", errors)])

        error_events = collector.of_type(ChannelErrorDetectedEvent)
        assert len(error_events) == 3

    @pytest.mark.asyncio
    async def test_enriched_fields_propagated(self):
        """Optional enriched fields from JustInError are passed to the event."""
        svc, collector = await _make_service()
        svc.add_new_channels(["KAM_1"])

        error = JustInError(
            date=100.0,
            errorCode=-8998,
            errorUIDescription="Dropped frames",
            errorDomain="TOAErrorDomainIOKit",
            errorUserInfo=JustInErrorInfo(
                NSLocalizedDescription="The input dropped 1 frames at 13:11:50:22"
            ),
            errorType=2,
        )
        await svc.update_channel_errors([("KAM_1", [error])])

        evt = collector.of_type(ChannelErrorDetectedEvent)[0]
        assert evt.error_domain == "TOAErrorDomainIOKit"
        assert evt.error_description == "The input dropped 1 frames at 13:11:50:22"
        assert evt.error_type == 2

    @pytest.mark.asyncio
    async def test_clear_resets_seen_errors(self):
        """After clear, the same error date triggers a new event."""
        svc, collector = await _make_service()
        svc.add_new_channels(["KAM_1"])

        error = JustInError(date=100.0, errorCode=1, errorUIDescription="err")
        await svc.update_channel_errors([("KAM_1", [error])])
        assert len(collector.of_type(ChannelErrorDetectedEvent)) == 1

        await svc.clear_all_errors()
        collector.events.clear()

        # Same error date re-appears after clear → should publish again
        await svc.update_channel_errors([("KAM_1", [error])])
        assert len(collector.of_type(ChannelErrorDetectedEvent)) == 1


# ── clear_all_errors ────────────────────────────────────────────────

class TestClearAllErrors:

    @pytest.mark.asyncio
    async def test_clears_errors_and_returns_count(self):
        svc, collector = await _make_service()
        svc.add_new_channels(["KAM_1", "KAM_2"])

        err = JustInError(date=100.0, errorCode=1, errorUIDescription="err")
        await svc.update_channel_errors([
            ("KAM_1", [err]),
            ("KAM_2", [err]),
        ])

        cleared = await svc.clear_all_errors()
        assert cleared == 2

        assert svc.get_channel_state("KAM_1").has_errors is False
        assert svc.get_channel_state("KAM_2").has_errors is False

    @pytest.mark.asyncio
    async def test_clear_with_no_errors_returns_zero(self):
        svc, _ = await _make_service()
        svc.add_new_channels(["KAM_1"])
        cleared = await svc.clear_all_errors()
        assert cleared == 0

    @pytest.mark.asyncio
    async def test_clear_publishes_status_update(self):
        svc, collector = await _make_service()
        svc.add_new_channels(["KAM_1"])

        err = JustInError(date=100.0, errorCode=1, errorUIDescription="err")
        await svc.update_channel_errors([("KAM_1", [err])])
        collector.events.clear()  # reset

        await svc.clear_all_errors()
        assert len(collector.of_type(IngestStatusUpdatedEvent)) == 1


# ── update_recording_paths / get_recording_paths ────────────────────

class TestRecordingPaths:

    @pytest.mark.asyncio
    async def test_update_publishes_event(self):
        svc, collector = await _make_service()
        changed = await svc.update_recording_paths("KAM_1", ["/rec/path1"], "Preset1")
        assert changed is True

        path_events = collector.of_type(RecordingPathsDiscoveredEvent)
        assert len(path_events) == 1
        assert path_events[0].channel_name == "KAM_1"
        assert path_events[0].paths == ("/rec/path1",)
        assert path_events[0].preset_name == "Preset1"

    @pytest.mark.asyncio
    async def test_same_paths_no_event(self):
        svc, collector = await _make_service()
        await svc.update_recording_paths("KAM_1", ["/rec/path1"], "Preset1")
        collector.events.clear()

        changed = await svc.update_recording_paths("KAM_1", ["/rec/path1"], "Preset1")
        assert changed is False
        assert len(collector.of_type(RecordingPathsDiscoveredEvent)) == 0

    @pytest.mark.asyncio
    async def test_get_recording_paths_snapshot(self):
        svc, _ = await _make_service()
        await svc.update_recording_paths("KAM_1", ["/a", "/b"], "P1")
        await svc.update_recording_paths("KAM_2", ["/c"], "P2")

        paths = svc.get_recording_paths()
        assert paths["KAM_1"]["paths"] == ["/a", "/b"]
        assert paths["KAM_1"]["preset_name"] == "P1"
        assert paths["KAM_2"]["paths"] == ["/c"]


# ── set_connection_status ───────────────────────────────────────────

class TestConnectionStatus:

    @pytest.mark.asyncio
    async def test_connect_publishes_online_event(self):
        svc, collector = await _make_service()
        assert svc.is_connected() is False

        await svc.set_connection_status(True)
        assert svc.is_connected() is True
        assert len(collector.of_type(IngestOnlineEvent)) == 1

    @pytest.mark.asyncio
    async def test_disconnect_publishes_offline_event(self):
        svc, collector = await _make_service()
        await svc.set_connection_status(True)
        collector.events.clear()

        await svc.set_connection_status(False)
        assert svc.is_connected() is False
        assert len(collector.of_type(IngestOfflineEvent)) == 1

    @pytest.mark.asyncio
    async def test_same_status_no_event(self):
        svc, collector = await _make_service()
        await svc.set_connection_status(False)  # already False
        assert len(collector.of_type(IngestOnlineEvent)) == 0
        assert len(collector.of_type(IngestOfflineEvent)) == 0


# ── update_active_channels ──────────────────────────────────────────

class TestUpdateActiveChannels:

    @pytest.mark.asyncio
    async def test_removes_inactive_channels(self):
        svc, _ = await _make_service()
        svc.add_new_channels(["KAM_1", "KAM_2", "KAM_3"])

        await svc.update_active_channels(["KAM_1", "KAM_3"])

        names = svc.get_channel_names()
        assert "KAM_2" not in names
        assert set(names) == {"KAM_1", "KAM_3"}

    @pytest.mark.asyncio
    async def test_none_input_is_noop(self):
        svc, _ = await _make_service()
        svc.add_new_channels(["KAM_1"])
        await svc.update_active_channels(None)
        assert svc.get_channel_names() == ["KAM_1"]

    @pytest.mark.asyncio
    async def test_adds_new_channels(self):
        svc, _ = await _make_service()
        await svc.update_active_channels(["KAM_1", "KAM_2"])
        assert set(svc.get_channel_names()) == {"KAM_1", "KAM_2"}


# ── clear_cache ─────────────────────────────────────────────────────

class TestClearCache:

    def test_clear_cache(self):
        svc = IngestStateService(DomainEventBus())
        svc.add_new_channels(["KAM_1"])
        svc._recording_paths["KAM_1"] = ["/a"]
        svc._recording_preset_names["KAM_1"] = "P1"

        svc.clear_cache()

        assert svc.get_channel_names() == []
        assert svc.get_recording_paths() == {}
