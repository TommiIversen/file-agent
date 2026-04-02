"""Tests for IngestMonitorWorker._fast_polling_loop — all branches."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.domains.ingest_monitor.worker import IngestMonitorWorker


@pytest.fixture
def deps():
    settings = MagicMock()
    settings.justin_fast_poll_interval_seconds = 0.01
    settings.justin_slow_poll_interval_seconds = 0.1
    api_client = AsyncMock()
    state_service = AsyncMock()
    # get_status_cache is sync, not async — use MagicMock
    state_service.get_status_cache = MagicMock(return_value={})
    state_service.is_connected = MagicMock(return_value=False)
    return settings, api_client, state_service


@pytest.fixture
def worker(deps):
    return IngestMonitorWorker(*deps)


async def _run_loop_once(worker):
    """Start the fast loop, let it run one iteration, then stop."""
    worker._running = True
    task = asyncio.create_task(worker._fast_polling_loop())
    await asyncio.sleep(0.05)
    worker._running = False
    await task


class TestFastPollingLoop:

    async def test_no_channels_skips_poll(self, worker, deps):
        """When cache is empty, loop sleeps without calling API."""
        _, api_client, state_service = deps
        state_service.get_status_cache.return_value = {}

        await _run_loop_once(worker)

        api_client.get_all_channel_statuses.assert_not_awaited()

    async def test_api_returns_statuses_sets_connected(self, worker, deps):
        """When API returns data, connection is set to True and statuses updated."""
        _, api_client, state_service = deps
        state_service.get_status_cache.return_value = {"CH1": {}, "CH2": {}}
        api_client.get_all_channel_statuses.return_value = [{"ch": "CH1"}, {"ch": "CH2"}]

        await _run_loop_once(worker)

        state_service.set_connection_status.assert_any_await(True)
        state_service.update_channel_statuses.assert_awaited()

    async def test_api_returns_none_sets_disconnected(self, worker, deps):
        """When API returns None, connection is set to False."""
        _, api_client, state_service = deps
        state_service.get_status_cache.return_value = {"CH1": {}}
        api_client.get_all_channel_statuses.return_value = None

        await _run_loop_once(worker)

        state_service.set_connection_status.assert_any_await(False)
        state_service.update_channel_statuses.assert_not_awaited()

    async def test_api_returns_empty_list_is_connected(self, worker, deps):
        """Empty list (not None) means API is reachable -> connected."""
        _, api_client, state_service = deps
        state_service.get_status_cache.return_value = {"CH1": {}}
        api_client.get_all_channel_statuses.return_value = []

        await _run_loop_once(worker)

        state_service.set_connection_status.assert_any_await(True)
        state_service.update_channel_statuses.assert_awaited_with([])

    async def test_cancelled_error_breaks_loop(self, worker, deps):
        """CancelledError exits the loop cleanly."""
        _, api_client, state_service = deps
        state_service.get_status_cache.return_value = {"CH1": {}}
        api_client.get_all_channel_statuses.side_effect = asyncio.CancelledError()

        worker._running = True
        task = asyncio.create_task(worker._fast_polling_loop())
        await asyncio.sleep(0.05)

        # Loop should have exited on its own
        assert task.done()

    async def test_generic_exception_sets_disconnected(self, worker, deps):
        """On unexpected error, connection is marked False and loop retries."""
        _, api_client, state_service = deps
        state_service.get_status_cache.return_value = {"CH1": {}}

        call_count = 0
        async def fail_then_ok(names):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("API boom")
            return [{"ch": "CH1"}]

        api_client.get_all_channel_statuses.side_effect = fail_then_ok

        await _run_loop_once(worker)

        # First call failed -> disconnected, second succeeded -> connected
        state_service.set_connection_status.assert_any_await(False)

    async def test_loop_respects_running_flag(self, worker, deps):
        """Setting _running=False stops the loop."""
        _, api_client, state_service = deps
        state_service.get_status_cache.return_value = {}

        worker._running = True
        task = asyncio.create_task(worker._fast_polling_loop())
        worker._running = False
        await asyncio.sleep(0.05)
        await task

        assert task.done()
