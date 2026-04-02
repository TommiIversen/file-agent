"""Tests for TallySwitchMonitorService._monitor_loop + _publish_status_events."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.domains.tally_light.monitor_service import TallySwitchMonitorService
from app.domains.tally_light.protocols import PowerSwitchType
from app.domains.tally_light.models import TallySwitchStatus


def _make_switch(is_online: bool = True):
    switch = AsyncMock()
    switch.is_online.return_value = is_online
    switch.switch_type = PowerSwitchType.MOCK
    return switch


@pytest.fixture
def event_bus():
    return AsyncMock()


@pytest.fixture
def service(event_bus):
    switch = _make_switch(is_online=True)
    return TallySwitchMonitorService(
        switch_client=switch,
        ip_address="192.168.1.100",
        event_bus=event_bus,
        check_interval_seconds=0,  # instant for tests
    )


# ------------------------------------------------------------------
# _monitor_loop
# ------------------------------------------------------------------

class TestMonitorLoop:

    async def test_loop_performs_checks_and_stops(self, service):
        """Loop runs, performs check, then stops when _is_running goes False."""
        check_count = 0
        original_check = service._perform_status_check

        async def counting_check():
            nonlocal check_count
            check_count += 1
            result = await original_check()
            if check_count >= 2:
                service._is_running = False
            return result

        service._perform_status_check = counting_check
        service._is_running = True
        await asyncio.wait_for(service._monitor_loop(), timeout=5.0)

        assert check_count >= 2
        assert service._is_running is False

    async def test_loop_continues_on_check_error(self, service, event_bus):
        """Single check failure doesn't kill the loop."""
        call_count = 0

        async def failing_then_stop():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient error")
            # Stop the loop on second call
            service._is_running = False

        service._perform_status_check = failing_then_stop
        service._is_running = True
        await asyncio.wait_for(service._monitor_loop(), timeout=5.0)

        assert call_count >= 2  # survived the error

    async def test_loop_exits_on_cancelled(self, service):
        """CancelledError breaks the loop cleanly."""
        async def cancel_immediately():
            raise asyncio.CancelledError()

        service._perform_status_check = cancel_immediately
        service._is_running = True
        await asyncio.wait_for(service._monitor_loop(), timeout=5.0)
        assert service._is_running is False


# ------------------------------------------------------------------
# _publish_status_events
# ------------------------------------------------------------------

class TestPublishStatusEvents:

    def _status(self, is_online: bool = True) -> TallySwitchStatus:
        return TallySwitchStatus(
            is_online=is_online,
            switch_type="mock",
            ip_address="192.168.1.100",
            last_checked=datetime.now(),
            error_message=None,
        )

    async def test_always_publishes_status_updated(self, service, event_bus):
        """StatusUpdated event is always published."""
        status = self._status(is_online=True)
        await service._publish_status_events(status, None)

        assert event_bus.publish.await_count >= 1

    async def test_publishes_online_event_on_first_check(self, service, event_bus):
        """First check (previous=None) with online -> OnlineEvent."""
        status = self._status(is_online=True)
        await service._publish_status_events(status, None)

        # Should have 2 calls: StatusUpdated + Online
        assert event_bus.publish.await_count == 2

    async def test_publishes_offline_event_on_transition(self, service, event_bus):
        """Online -> Offline transition -> OfflineEvent."""
        prev = self._status(is_online=True)
        new = self._status(is_online=False)
        await service._publish_status_events(new, prev)

        assert event_bus.publish.await_count == 2

    async def test_no_transition_event_when_same(self, service, event_bus):
        """Same status -> only StatusUpdated, no Online/Offline."""
        prev = self._status(is_online=True)
        new = self._status(is_online=True)
        await service._publish_status_events(new, prev)

        assert event_bus.publish.await_count == 1

    async def test_exception_in_publish_is_caught(self, service, event_bus):
        """Exception during publish doesn't crash."""
        event_bus.publish.side_effect = RuntimeError("bus error")
        status = self._status(is_online=True)

        # Should not raise
        await service._publish_status_events(status, None)
