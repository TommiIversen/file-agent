"""Tests for IngestMonitorWorker.stop_monitoring — all branches."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.domains.ingest_monitor.worker import IngestMonitorWorker


@pytest.fixture
def deps():
    settings = MagicMock()
    settings.justin_fast_poll_interval_seconds = 0.05
    settings.justin_slow_poll_interval_seconds = 0.1
    api_client = AsyncMock()
    state_service = MagicMock()
    state_service.get_status_cache.return_value = {}
    state_service.is_connected.return_value = False
    return settings, api_client, state_service


@pytest.fixture
def worker(deps):
    return IngestMonitorWorker(*deps)


class TestStopMonitoring:
    async def test_not_running_returns_early(self, worker):
        """Branch: _running is False -> logs warning and returns."""
        assert worker._running is False
        await worker.stop_monitoring()
        # Should not raise, just return

    async def test_sets_running_false(self, worker, deps):
        """Branch: _running is True -> sets to False."""
        worker._running = True
        worker._fast_loop_task = None
        worker._slow_loop_task = None
        _, api_client, _ = deps

        await worker.stop_monitoring()

        assert worker._running is False
        api_client.close.assert_awaited_once()

    async def test_cancels_fast_loop_task(self, worker, deps):
        """Branch: fast loop task is running -> cancel it."""
        worker._running = True
        _, api_client, _ = deps

        async def forever():
            await asyncio.sleep(100)

        worker._fast_loop_task = asyncio.create_task(forever())
        worker._slow_loop_task = None
        await asyncio.sleep(0)  # let task start

        await worker.stop_monitoring()

        assert worker._fast_loop_task.cancelled()
        api_client.close.assert_awaited_once()

    async def test_cancels_slow_loop_task(self, worker, deps):
        """Branch: slow loop task is running -> cancel it."""
        worker._running = True
        _, api_client, _ = deps

        async def forever():
            await asyncio.sleep(100)

        worker._fast_loop_task = None
        worker._slow_loop_task = asyncio.create_task(forever())
        await asyncio.sleep(0)

        await worker.stop_monitoring()

        assert worker._slow_loop_task.cancelled()

    async def test_cancels_both_tasks(self, worker, deps):
        """Branch: both tasks running -> cancel both."""
        worker._running = True
        _, api_client, _ = deps

        async def forever():
            await asyncio.sleep(100)

        worker._fast_loop_task = asyncio.create_task(forever())
        worker._slow_loop_task = asyncio.create_task(forever())
        await asyncio.sleep(0)

        await worker.stop_monitoring()

        assert worker._fast_loop_task.cancelled()
        assert worker._slow_loop_task.cancelled()
        api_client.close.assert_awaited_once()

    async def test_already_done_tasks_not_cancelled(self, worker, deps):
        """Branch: tasks are already done -> skip cancel."""
        worker._running = True
        _, api_client, _ = deps

        async def instant():
            return

        fast = asyncio.create_task(instant())
        slow = asyncio.create_task(instant())
        await asyncio.sleep(0)  # let them finish

        worker._fast_loop_task = fast
        worker._slow_loop_task = slow

        assert fast.done()
        assert slow.done()

        await worker.stop_monitoring()
        api_client.close.assert_awaited_once()

    async def test_closes_api_client(self, worker, deps):
        """Ensure api_client.close() is always called."""
        worker._running = True
        worker._fast_loop_task = None
        worker._slow_loop_task = None
        _, api_client, _ = deps

        await worker.stop_monitoring()

        api_client.close.assert_awaited_once()
