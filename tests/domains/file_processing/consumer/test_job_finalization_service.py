"""
Tests for JobFinalizationService — handles completion of copy jobs.
Tests success, failure, max-retry paths and edge cases.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.domains.file_processing.consumer.job_finalization_service import JobFinalizationService
from app.domains.file_processing.consumer.job_models import QueueJob
from app.models import TrackedFile, FileStatus
from app.core.events.file_events import FileCopyCompletedEvent


def _make_job(file_id: str = "test-id", file_path: str = "/test/file.mxf", file_size: int = 1000) -> QueueJob:
    return QueueJob(
        file_id=file_id,
        file_path=file_path,
        file_size=file_size,
        creation_time=datetime.now(),
        is_growing_at_queue_time=False,
        added_to_queue_at=datetime.now(),
    )


def _make_tracked(file_id: str = "test-id", status: FileStatus = FileStatus.COPYING) -> TrackedFile:
    return TrackedFile(
        id=file_id,
        file_path="/test/file.mxf",
        file_size=1000,
        status=status,
    )


def _make_service():
    settings = MagicMock()
    settings.max_retry_attempts = 3
    repo = MagicMock()
    repo.get_by_id = AsyncMock()
    event_bus = MagicMock()
    event_bus.publish = AsyncMock()
    state_machine = MagicMock()
    state_machine.transition = AsyncMock()

    svc = JobFinalizationService(settings, repo, event_bus, state_machine)
    return svc, repo, event_bus, state_machine


class TestFinalizeSuccess:

    @pytest.mark.asyncio
    async def test_success_transitions_to_completed(self):
        svc, repo, event_bus, sm = _make_service()
        tracked = _make_tracked()
        repo.get_by_id.return_value = tracked

        await svc.finalize_success(_make_job(), file_size=5000)

        sm.transition.assert_awaited_once_with(
            file_id="test-id",
            new_status=FileStatus.COMPLETED,
            copy_progress=100.0,
        )

    @pytest.mark.asyncio
    async def test_success_publishes_completed_event(self):
        svc, repo, event_bus, sm = _make_service()
        tracked = _make_tracked()
        repo.get_by_id.return_value = tracked

        await svc.finalize_success(_make_job(), file_size=5000)

        event_bus.publish.assert_awaited()
        event = event_bus.publish.call_args[0][0]
        assert isinstance(event, FileCopyCompletedEvent)
        assert event.file_id == "test-id"
        assert event.bytes_copied == 5000

    @pytest.mark.asyncio
    async def test_success_passes_fields_via_kwargs_not_mutation(self):
        """Fields must be passed as kwargs to state_machine.transition, not mutated directly."""
        svc, repo, event_bus, sm = _make_service()
        tracked = _make_tracked()
        repo.get_by_id.return_value = tracked

        await svc.finalize_success(_make_job(), file_size=5000)

        # Verify copy_progress is passed via kwargs
        call_kwargs = sm.transition.call_args[1]
        assert call_kwargs["copy_progress"] == 100.0
        # completed_at and error_message are handled automatically by state machine

    @pytest.mark.asyncio
    async def test_success_skips_if_already_delete_failed(self):
        svc, repo, event_bus, sm = _make_service()
        tracked = _make_tracked(status=FileStatus.COMPLETED_DELETE_FAILED)
        repo.get_by_id.return_value = tracked

        await svc.finalize_success(_make_job(), file_size=5000)

        sm.transition.assert_not_awaited()
        event_bus.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_success_skips_if_file_not_found(self):
        svc, repo, event_bus, sm = _make_service()
        repo.get_by_id.return_value = None

        await svc.finalize_success(_make_job(), file_size=5000)

        sm.transition.assert_not_awaited()


class TestFinalizeFailure:

    @pytest.mark.asyncio
    async def test_failure_transitions_to_failed(self):
        svc, repo, event_bus, sm = _make_service()
        tracked = _make_tracked()
        repo.get_by_id.return_value = tracked

        await svc.finalize_failure(_make_job(), RuntimeError("disk error"))

        sm.transition.assert_awaited_once_with(
            file_id="test-id",
            new_status=FileStatus.FAILED,
            error_message="disk error",
        )

    @pytest.mark.asyncio
    async def test_failure_passes_error_via_kwargs(self):
        svc, repo, event_bus, sm = _make_service()
        tracked = _make_tracked()
        repo.get_by_id.return_value = tracked

        await svc.finalize_failure(_make_job(), RuntimeError("disk error"))

        sm.transition.assert_awaited_once_with(
            file_id="test-id",
            new_status=FileStatus.FAILED,
            error_message="disk error",
        )

    @pytest.mark.asyncio
    async def test_failure_skips_if_file_not_found(self):
        svc, repo, event_bus, sm = _make_service()
        repo.get_by_id.return_value = None

        await svc.finalize_failure(_make_job(), RuntimeError("err"))

        sm.transition.assert_not_awaited()


class TestFinalizeMaxRetries:

    @pytest.mark.asyncio
    async def test_max_retries_transitions_to_failed(self):
        svc, repo, event_bus, sm = _make_service()
        tracked = _make_tracked()
        repo.get_by_id.return_value = tracked

        await svc.finalize_max_retries(_make_job())

        sm.transition.assert_awaited_once_with(
            file_id="test-id",
            new_status=FileStatus.FAILED,
            error_message="Failed after 3 retry attempts",
        )

    @pytest.mark.asyncio
    async def test_max_retries_passes_error_via_kwargs(self):
        svc, repo, event_bus, sm = _make_service()
        tracked = _make_tracked()
        repo.get_by_id.return_value = tracked

        await svc.finalize_max_retries(_make_job())

        call_kwargs = sm.transition.call_args[1]
        assert call_kwargs["error_message"] == "Failed after 3 retry attempts"
        assert call_kwargs["new_status"] == FileStatus.FAILED

    @pytest.mark.asyncio
    async def test_max_retries_skips_if_file_not_found(self):
        svc, repo, event_bus, sm = _make_service()
        repo.get_by_id.return_value = None

        await svc.finalize_max_retries(_make_job())

        sm.transition.assert_not_awaited()


class TestFinalizationInfo:

    def test_get_finalization_info(self):
        svc, _, _, _ = _make_service()
        info = svc.get_finalization_info()
        assert info["max_retry_attempts"] == 3
        assert info["file_repository_available"] is True
        assert info["state_machine_available"] is True
