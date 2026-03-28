"""Tests for TallyLightEventHandler — state transitions and blinker task."""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.domains.tally_light.event_handlers import TallyLightEventHandler, TallyState
from app.domains.tally_light.protocols import PowerSwitchError, PowerSwitchType
from app.domains.ingest_monitor.events import IngestStatusUpdatedEvent, AutoStopWarningEvent


# ── Helpers ──────────────────────────────────────────────────────

class FakePowerSwitch:
    """In-memory power switch for testing — no HTTP calls."""

    def __init__(self):
        self.is_on = False
        self.on_calls = 0
        self.off_calls = 0
        self.closed = False

    async def turn_on(self) -> bool:
        self.on_calls += 1
        self.is_on = True
        return True

    async def turn_off(self) -> bool:
        self.off_calls += 1
        self.is_on = False
        return True

    async def get_status(self) -> bool:
        return self.is_on

    async def is_online(self) -> bool:
        return True

    async def close(self) -> None:
        self.closed = True

    @property
    def switch_type(self) -> PowerSwitchType:
        return PowerSwitchType.MOCK


def _make_settings():
    """Create a mock Settings with tally-light fields."""
    s = MagicMock()
    s.tally_light_switch_type = "mock"
    s.tally_light_switch_ip = "10.0.0.1"
    s.tally_light_blink_interval_seconds = 0.05  # Fast for tests
    s.tally_light_api_timeout_seconds = 1.0
    return s


def _make_handler(switch=None):
    """Create a TallyLightEventHandler with a fake power switch."""
    settings = _make_settings()
    with patch("app.domains.tally_light.event_handlers.create_power_switch", return_value=switch or FakePowerSwitch()):
        handler = TallyLightEventHandler(settings)
    return handler


def _ingest_event(channels: dict[str, bool] | None = None) -> IngestStatusUpdatedEvent:
    """Create an IngestStatusUpdatedEvent from a dict of channel_name -> is_recording."""
    if channels is None:
        snapshot = {}
    else:
        snapshot = {name: {"is_recording": rec} for name, rec in channels.items()}
    return IngestStatusUpdatedEvent(status_snapshot=snapshot)


# ── State transition tests ───────────────────────────────────────

class TestIngestStatusTransitions:
    @pytest.mark.asyncio
    async def test_no_channels_sets_off(self):
        handler = _make_handler()
        await handler.handle_ingest_status_update(_ingest_event({}))
        assert handler.get_current_state() == TallyState.OFF

    @pytest.mark.asyncio
    async def test_all_recording_sets_solid_on(self):
        switch = FakePowerSwitch()
        handler = _make_handler(switch)

        await handler.handle_ingest_status_update(
            _ingest_event({"KAM_1": True, "KAM_2": True})
        )
        assert handler.get_current_state() == TallyState.SOLID_ON
        assert switch.on_calls == 1

    @pytest.mark.asyncio
    async def test_some_recording_sets_blinking(self):
        handler = _make_handler()

        await handler.handle_ingest_status_update(
            _ingest_event({"KAM_1": True, "KAM_2": False})
        )
        assert handler.get_current_state() == TallyState.BLINKING
        assert handler.is_blinking()
        # Cleanup
        await handler.stop_worker()

    @pytest.mark.asyncio
    async def test_none_recording_sets_off(self):
        switch = FakePowerSwitch()
        handler = _make_handler(switch)

        await handler.handle_ingest_status_update(
            _ingest_event({"KAM_1": False, "KAM_2": False})
        )
        assert handler.get_current_state() == TallyState.OFF

    @pytest.mark.asyncio
    async def test_empty_snapshot_sets_off(self):
        handler = _make_handler()
        event = IngestStatusUpdatedEvent(status_snapshot={})
        await handler.handle_ingest_status_update(event)
        assert handler.get_current_state() == TallyState.OFF

    @pytest.mark.asyncio
    async def test_no_state_change_skips_update(self):
        switch = FakePowerSwitch()
        handler = _make_handler(switch)

        # First call: OFF → OFF (no change from initial state)
        await handler.handle_ingest_status_update(_ingest_event({}))
        assert switch.off_calls == 0  # No call since already OFF

    @pytest.mark.asyncio
    async def test_solid_on_to_off(self):
        switch = FakePowerSwitch()
        handler = _make_handler(switch)

        await handler.handle_ingest_status_update(
            _ingest_event({"KAM_1": True})
        )
        assert handler.get_current_state() == TallyState.SOLID_ON

        await handler.handle_ingest_status_update(
            _ingest_event({"KAM_1": False})
        )
        assert handler.get_current_state() == TallyState.OFF
        assert switch.off_calls >= 1


class TestAutoStopWarning:
    @pytest.mark.asyncio
    async def test_auto_stop_warning_forces_blinking(self):
        handler = _make_handler()

        # First put into SOLID_ON
        await handler.handle_ingest_status_update(
            _ingest_event({"KAM_1": True})
        )
        assert handler.get_current_state() == TallyState.SOLID_ON

        # Auto-stop warning should force BLINKING
        event = AutoStopWarningEvent(
            channel_name="KAM_1",
            recording_seconds=3400,
            limit_seconds=3600,
            remaining_seconds=200,
        )
        await handler.handle_auto_stop_warning(event)
        assert handler.get_current_state() == TallyState.BLINKING
        assert handler._auto_stop_warning_active is True
        await handler.stop_worker()

    @pytest.mark.asyncio
    async def test_auto_stop_warning_blocks_normal_updates(self):
        handler = _make_handler()

        # Set auto-stop warning active with blinking
        event = AutoStopWarningEvent(
            channel_name="KAM_1",
            recording_seconds=3400,
            limit_seconds=3600,
            remaining_seconds=200,
        )
        await handler.handle_auto_stop_warning(event)

        # Normal ingest update with recording should be ignored
        await handler.handle_ingest_status_update(
            _ingest_event({"KAM_1": True})
        )
        # Still blinking (warning owns the state)
        assert handler.get_current_state() == TallyState.BLINKING
        await handler.stop_worker()

    @pytest.mark.asyncio
    async def test_auto_stop_warning_cleared_when_no_recording(self):
        switch = FakePowerSwitch()
        handler = _make_handler(switch)

        # Set warning active
        event = AutoStopWarningEvent(
            channel_name="KAM_1",
            recording_seconds=3400,
            limit_seconds=3600,
            remaining_seconds=200,
        )
        await handler.handle_auto_stop_warning(event)
        assert handler._auto_stop_warning_active is True

        # Stop all recording — should clear the flag and process normally
        await handler.handle_ingest_status_update(
            _ingest_event({"KAM_1": False})
        )
        assert handler._auto_stop_warning_active is False
        await handler.stop_worker()


class TestBlinkerTask:
    @pytest.mark.asyncio
    async def test_blinker_toggles_on_off(self):
        switch = FakePowerSwitch()
        handler = _make_handler(switch)

        await handler.handle_ingest_status_update(
            _ingest_event({"KAM_1": True, "KAM_2": False})
        )
        # Let the blinker run a few cycles
        await asyncio.sleep(0.15)

        assert switch.on_calls >= 1
        assert switch.off_calls >= 1
        await handler.stop_worker()

    @pytest.mark.asyncio
    async def test_blinker_stops_on_state_change(self):
        switch = FakePowerSwitch()
        handler = _make_handler(switch)

        # Start blinking
        await handler.handle_ingest_status_update(
            _ingest_event({"KAM_1": True, "KAM_2": False})
        )
        assert handler.is_blinking()

        # Transition to SOLID_ON
        await handler.handle_ingest_status_update(
            _ingest_event({"KAM_1": True, "KAM_2": True})
        )
        assert handler.get_current_state() == TallyState.SOLID_ON
        assert not handler.is_blinking()
        await handler.stop_worker()

    @pytest.mark.asyncio
    async def test_blinker_loop_error_resets_to_off(self):
        """If blinker loop crashes, state resets to OFF."""
        switch = FakePowerSwitch()
        call_count = 0
        original_turn_on = switch.turn_on

        async def failing_turn_on():
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise RuntimeError("Simulated hardware failure")
            return await original_turn_on()

        switch.turn_on = failing_turn_on
        handler = _make_handler(switch)

        await handler.handle_ingest_status_update(
            _ingest_event({"KAM_1": True, "KAM_2": False})
        )
        # Wait for blinker to crash
        await asyncio.sleep(0.2)

        assert handler.get_current_state() == TallyState.OFF
        await handler.stop_worker()


class TestPowerSwitchError:
    @pytest.mark.asyncio
    async def test_power_switch_error_preserves_old_state(self):
        """If turn_on raises PowerSwitchError, state doesn't change."""
        switch = FakePowerSwitch()

        async def failing_turn_on():
            raise PowerSwitchError("Connection refused")

        switch.turn_on = failing_turn_on
        handler = _make_handler(switch)

        # Try to go SOLID_ON — should fail
        await handler.handle_ingest_status_update(
            _ingest_event({"KAM_1": True})
        )
        # State should remain OFF because the switch failed
        assert handler.get_current_state() == TallyState.OFF


class TestStopWorker:
    @pytest.mark.asyncio
    async def test_stop_worker_turns_off_and_closes(self):
        switch = FakePowerSwitch()
        handler = _make_handler(switch)

        # Start SOLID_ON
        await handler.handle_ingest_status_update(
            _ingest_event({"KAM_1": True})
        )

        await handler.stop_worker()
        assert handler.get_current_state() == TallyState.OFF
        assert switch.closed is True

    @pytest.mark.asyncio
    async def test_stop_worker_cancels_blinker(self):
        handler = _make_handler()

        # Start blinking
        await handler.handle_ingest_status_update(
            _ingest_event({"KAM_1": True, "KAM_2": False})
        )
        assert handler.is_blinking()

        await handler.stop_worker()
        assert not handler.is_blinking()
        assert handler.get_current_state() == TallyState.OFF


class TestHelperMethods:
    def test_get_current_state_initial(self):
        handler = _make_handler()
        assert handler.get_current_state() == TallyState.OFF

    def test_is_blinking_initial(self):
        handler = _make_handler()
        assert handler.is_blinking() is False
