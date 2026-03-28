"""Tests for JobQueueService — queue operations, network recovery, job lifecycle."""
import asyncio
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from app.domains.file_processing.job_queue import JobQueueService
from app.domains.file_processing.consumer.job_models import QueueJob
from app.core.exceptions import InvalidTransitionError
from app.models import TrackedFile, FileStatus


def _settings():
    s = MagicMock()
    return s


def _job(file_id="f1", path="/src/test.mxf", size=1000, **kw):
    defaults = dict(
        file_id=file_id,
        file_path=path,
        file_size=size,
        creation_time=datetime(2026, 1, 1),
        is_growing_at_queue_time=False,
        added_to_queue_at=datetime.now(),
    )
    defaults.update(kw)
    return QueueJob(**defaults)


def _tf(file_id="f1", path="/src/test.mxf", status=FileStatus.WAITING_FOR_NETWORK, **kw):
    defaults = dict(id=file_id, file_path=path, file_size=1000, status=status)
    defaults.update(kw)
    return TrackedFile(**defaults)


@pytest.fixture
def deps():
    return dict(
        settings=_settings(),
        file_repository=AsyncMock(),
        event_bus=AsyncMock(),
        state_machine=AsyncMock(),
    )


@pytest.fixture
def svc(deps):
    s = JobQueueService(**deps)
    s.job_queue = asyncio.PriorityQueue()
    return s


# ── Queue operations ────────────────────────────────────────────

class TestGetNextJob:
    @pytest.mark.asyncio
    async def test_returns_job_from_queue(self, svc):
        job = _job()
        await svc.job_queue.put(job)

        result = await svc.get_next_job()
        assert result is job
        assert svc._total_jobs_processed == 1

    @pytest.mark.asyncio
    async def test_returns_none_on_timeout(self, svc):
        result = await svc.get_next_job()
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_if_queue_is_none(self, svc):
        svc.job_queue = None
        result = await svc.get_next_job()
        assert result is None


class TestMarkJobCompleted:
    @pytest.mark.asyncio
    async def test_calls_task_done(self, svc):
        job = _job()
        await svc.job_queue.put(job)
        await svc.job_queue.get()  # Must get before task_done

        await svc.mark_job_completed(job, processing_time=1.5)
        # task_done doesn't raise = success

    @pytest.mark.asyncio
    async def test_no_queue_does_nothing(self, svc):
        svc.job_queue = None
        await svc.mark_job_completed(_job())  # Should not raise


class TestMarkJobFailed:
    @pytest.mark.asyncio
    async def test_increments_retry_and_records(self, svc):
        job = _job()
        await svc.job_queue.put(job)
        await svc.job_queue.get()

        await svc.mark_job_failed(job, "disk error", processing_time=0.5)

        assert job.retry_count == 1
        assert job.last_error_message == "disk error"
        assert len(svc._failed_jobs) == 1

    @pytest.mark.asyncio
    async def test_failed_jobs_list_capped_at_100(self, svc):
        # Pre-fill with 100 results
        for i in range(100):
            svc._failed_jobs.append(MagicMock())

        job = _job()
        await svc.job_queue.put(job)
        await svc.job_queue.get()

        await svc.mark_job_failed(job, "overflow")
        assert len(svc._failed_jobs) == 100  # Capped

    @pytest.mark.asyncio
    async def test_no_queue_does_nothing(self, svc):
        svc.job_queue = None
        await svc.mark_job_failed(_job(), "err")


# ── Network recovery ────────────────────────────────────────────

class TestProcessWaitingNetworkFiles:
    @pytest.mark.asyncio
    async def test_reactivates_waiting_files(self, svc, deps):
        tf = _tf(growth_rate_mbps=0.0)
        deps["file_repository"].get_all.return_value = [tf]

        await svc.process_waiting_network_files()

        deps["state_machine"].transition.assert_awaited_once()
        call_kwargs = deps["state_machine"].transition.call_args[1]
        assert call_kwargs["new_status"] == FileStatus.DISCOVERED

    @pytest.mark.asyncio
    async def test_growing_file_goes_to_ready_to_start_growing(self, svc, deps):
        tf = _tf(growth_rate_mbps=5.0)
        deps["file_repository"].get_all.return_value = [tf]

        await svc.process_waiting_network_files()

        call_kwargs = deps["state_machine"].transition.call_args[1]
        assert call_kwargs["new_status"] == FileStatus.READY_TO_START_GROWING

    @pytest.mark.asyncio
    async def test_no_waiting_files_does_nothing(self, svc, deps):
        deps["file_repository"].get_all.return_value = []

        await svc.process_waiting_network_files()
        deps["state_machine"].transition.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalid_transition_is_logged_not_raised(self, svc, deps):
        tf = _tf()
        deps["file_repository"].get_all.return_value = [tf]
        deps["state_machine"].transition.side_effect = InvalidTransitionError(
            "f.mxf", "WaitingForNetwork", "Discovered"
        )

        # Should not raise
        await svc.process_waiting_network_files()

    @pytest.mark.asyncio
    async def test_generic_error_is_logged_not_raised(self, svc, deps):
        tf = _tf()
        deps["file_repository"].get_all.return_value = [tf]
        deps["state_machine"].transition.side_effect = RuntimeError("boom")

        await svc.process_waiting_network_files()


class TestHandleDestinationUnavailable:
    @pytest.mark.asyncio
    async def test_does_not_raise(self, svc):
        # This is currently a no-op that logs, just verify it doesn't crash
        await svc.handle_destination_unavailable()


# ── Producer lifecycle ───────────────────────────────────────────

class TestProducerLifecycle:
    @pytest.mark.asyncio
    async def test_stop_producer_sets_running_false(self, svc):
        svc._running = True
        svc.stop_producer()
        assert svc._running is False

    def test_get_queue_returns_queue(self, svc):
        assert svc.get_queue() is svc.job_queue

    def test_get_queue_returns_none_when_uninitialized(self, deps):
        s = JobQueueService(**deps)
        assert s.get_queue() is None
