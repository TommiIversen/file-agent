"""
Tests for LifecycleService — the background pruning scheduler.
Tests start/stop lifecycle, command dispatching, and error handling.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.domains.lifecycle.service import LifecycleService
from app.domains.lifecycle.commands import PruneOldFilesCommand


def _make_service(keep_files_hours: int = 168, prune_interval: float = 0.05) -> tuple:
    """Create a LifecycleService with a very short interval for testing."""
    command_bus = MagicMock()
    command_bus.execute = AsyncMock()
    settings = MagicMock()
    settings.keep_files_hours = keep_files_hours

    service = LifecycleService(command_bus, settings)
    service._prune_interval_seconds = prune_interval  # short for tests
    return service, command_bus


class TestLifecycleServiceStartStop:

    @pytest.mark.asyncio
    async def test_start_sets_running(self):
        service, bus = _make_service()
        task = asyncio.create_task(service.start_pruning_loop())
        await asyncio.sleep(0.02)
        assert service.is_running() is True
        service.stop_pruning_loop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_stop_sets_not_running(self):
        service, bus = _make_service()
        task = asyncio.create_task(service.start_pruning_loop())
        await asyncio.sleep(0.02)
        service.stop_pruning_loop()
        assert service.is_running() is False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_double_start_is_noop(self):
        service, bus = _make_service()
        service._running = True
        # Calling start again should return immediately
        await service.start_pruning_loop()
        # If we get here without blocking, the guard worked

    def test_is_running_false_by_default(self):
        service, _ = _make_service()
        assert service.is_running() is False


class TestLifecycleServiceExecution:

    @pytest.mark.asyncio
    async def test_dispatches_prune_command(self):
        service, bus = _make_service(keep_files_hours=336, prune_interval=0.01)
        task = asyncio.create_task(service.start_pruning_loop())

        # Wait long enough for at least one prune cycle
        await asyncio.sleep(0.1)
        service.stop_pruning_loop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert bus.execute.call_count >= 1
        cmd = bus.execute.call_args[0][0]
        assert isinstance(cmd, PruneOldFilesCommand)
        assert cmd.hours_to_keep == 336

    @pytest.mark.asyncio
    async def test_continues_after_handler_error(self):
        service, bus = _make_service(prune_interval=0.01)
        call_count = 0

        async def failing_then_ok(cmd):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient error")

        bus.execute = failing_then_ok

        # We need the mock sleep to still yield to the event loop,
        # otherwise the while-loop starves the test coroutine.
        real_sleep = asyncio.sleep

        async def instant_sleep(seconds):
            await real_sleep(0)  # yield but don't wait

        with patch("app.domains.lifecycle.service.asyncio.sleep", side_effect=instant_sleep):
            task = asyncio.create_task(service.start_pruning_loop())
            await real_sleep(0.15)

            service.stop_pruning_loop()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # First call raised, service recovered and called again
        assert call_count >= 2


class TestLifecycleServiceConfig:

    def test_default_prune_interval_is_6_hours(self):
        service, _ = _make_service()
        # Reset to default — constructor sets 6 * 3600
        fresh_service = LifecycleService(MagicMock(), MagicMock())
        assert fresh_service._prune_interval_seconds == 6 * 3600
