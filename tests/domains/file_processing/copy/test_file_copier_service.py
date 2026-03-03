"""
Tests for FileCopierService - manages copy worker tasks.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.domains.file_processing.copy.file_copier_service import FileCopierService


@pytest.fixture
def settings():
    s = Settings()
    s.max_concurrent_copies = 2
    return s


@pytest.fixture
def job_queue():
    q = MagicMock()
    q.get_next_job = AsyncMock(return_value=None)  # Empty queue by default
    return q


@pytest.fixture
def command_bus():
    bus = MagicMock()
    bus.execute = AsyncMock()
    return bus


@pytest.fixture
def service(settings, job_queue, command_bus):
    return FileCopierService(settings, job_queue, command_bus)


class TestFileCopierServiceInit:

    def test_initial_state(self, service):
        assert service._running is False
        assert service._workers == []
        assert service._worker_count == 2


class TestStartWorkers:

    async def test_start_creates_workers(self, service):
        await service.start_workers()
        try:
            assert service._running is True
            assert len(service._workers) == 2
            for task in service._workers:
                assert isinstance(task, asyncio.Task)
        finally:
            await service.stop_workers()

    async def test_start_twice_is_noop(self, service):
        await service.start_workers()
        try:
            first_workers = list(service._workers)
            await service.start_workers()  # Should log warning and return
            assert service._workers == first_workers  # Same workers
        finally:
            await service.stop_workers()


class TestStopWorkers:

    async def test_stop_clears_workers(self, service):
        await service.start_workers()
        assert service._running is True

        await service.stop_workers()
        assert service._running is False
        assert service._workers == []

    async def test_stop_when_not_running_is_noop(self, service):
        await service.stop_workers()  # Should not raise
        assert service._running is False


class TestWorkerLoop:

    async def test_worker_processes_job_via_command_bus(self, service, job_queue, command_bus):
        """Worker picks a job from queue and dispatches via CommandBus."""
        call_count = 0

        async def fake_get_next_job():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                job = MagicMock()
                job.tracked_file = MagicMock()
                return job
            # After first job, stop the service
            service._running = False
            return None

        job_queue.get_next_job = AsyncMock(side_effect=fake_get_next_job)

        await service.start_workers()
        # Give workers time to pick up the job
        await asyncio.sleep(0.3)
        await service.stop_workers()

        # CommandBus should have been called at least once
        assert command_bus.execute.call_count >= 1
