"""Tests for IngestMonitorWorker._slow_polling_loop."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.domains.ingest_monitor.worker import IngestMonitorWorker


@pytest.fixture
def deps():
    settings = MagicMock()
    settings.justin_fast_poll_interval_seconds = 0.1
    settings.justin_slow_poll_interval_seconds = 0.01  # fast for tests
    api_client = AsyncMock()
    state_service = AsyncMock()
    state_service.get_status_cache = MagicMock(return_value={})
    state_service.is_connected = MagicMock(return_value=False)
    return settings, api_client, state_service


@pytest.fixture
def worker(deps):
    return IngestMonitorWorker(*deps)


async def _run_loop_once(worker):
    """Start slow loop, let it run one iteration, then stop."""
    worker._running = True
    task = asyncio.create_task(worker._slow_polling_loop())
    await asyncio.sleep(0.08)
    worker._running = False
    await task


# ── _slow_polling_loop ──────────────────────────────────────────

class TestSlowPollingLoop:

    async def test_active_channels_sets_connected(self, worker, deps):
        _, api_client, state_service = deps
        api_client.get_active_channels.return_value = ["CH1"]
        state_service.get_status_cache.return_value = {"CH1": {}}
        api_client.get_all_channel_errors.return_value = {}

        await _run_loop_once(worker)

        state_service.set_connection_status.assert_any_await(True)
        state_service.update_active_channels.assert_awaited()

    async def test_active_channels_none_sets_disconnected(self, worker, deps):
        _, api_client, state_service = deps
        api_client.get_active_channels.return_value = None

        await _run_loop_once(worker)

        state_service.set_connection_status.assert_any_await(False)
        state_service.update_active_channels.assert_not_awaited()

    async def test_fetches_errors_when_channels_exist(self, worker, deps):
        _, api_client, state_service = deps
        api_client.get_active_channels.return_value = ["CH1"]
        state_service.get_status_cache.return_value = {"CH1": {}}
        api_client.get_all_channel_errors.return_value = {"CH1": []}

        await _run_loop_once(worker)

        api_client.get_all_channel_errors.assert_awaited()
        state_service.update_channel_errors.assert_awaited()

    async def test_skips_errors_when_no_channels(self, worker, deps):
        _, api_client, state_service = deps
        api_client.get_active_channels.return_value = []
        state_service.get_status_cache.return_value = {}

        await _run_loop_once(worker)

        api_client.get_all_channel_errors.assert_not_awaited()

    async def test_cancelled_error_breaks_loop(self, worker, deps):
        _, api_client, _ = deps
        api_client.get_active_channels.side_effect = asyncio.CancelledError()

        worker._running = True
        task = asyncio.create_task(worker._slow_polling_loop())
        await asyncio.sleep(0.08)

        assert task.done()

    async def test_generic_exception_sets_disconnected(self, worker, deps):
        _, api_client, state_service = deps

        call_count = 0
        async def fail_then_ok():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("API down")
            return []

        api_client.get_active_channels.side_effect = fail_then_ok

        await _run_loop_once(worker)

        state_service.set_connection_status.assert_any_await(False)

    async def test_stops_when_running_cleared_during_sleep(self, worker, deps):
        """If _running is set to False during the initial sleep, loop exits."""
        worker._running = True
        task = asyncio.create_task(worker._slow_polling_loop())
        # Immediately clear running — loop should exit after its first sleep
        worker._running = False
        await asyncio.sleep(0.05)
        await task

        assert task.done()
