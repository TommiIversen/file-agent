"""
Simple tests for JobFinalizationService - follows 2:1 line ratio rule.

Tests job completion workflows (success/failure/retries).
Max 70 lines for 139-line service.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from app.services.consumer.job_finalization_service import JobFinalizationService
from app.models import FileStatus
from app.models import TrackedFile
from app.services.consumer.job_models import QueueJob
from app.core.file_repository import FileRepository
from app.core.file_state_machine import FileStateMachine
from app.core.events.event_bus import DomainEventBus


@pytest.fixture
def finalizer():
    """Simple finalizer for testing."""
    settings = MagicMock(max_retry_attempts=3)
    file_repository = AsyncMock(spec=FileRepository)
    state_machine = AsyncMock(spec=FileStateMachine)
    event_bus = AsyncMock(spec=DomainEventBus)

    return JobFinalizationService(settings, file_repository, event_bus, state_machine)


class TestJobFinalizationService:
    """Simple, focused tests for job finalization."""

    @pytest.mark.asyncio
    async def test_finalize_success(self, finalizer):
        """Test successful job completion."""
        tracked_file = TrackedFile(
            file_path="/test/file.txt", file_size=100, status=FileStatus.READY
        )
        job = QueueJob(
            file_id=tracked_file.id,
            file_path=tracked_file.file_path,
            file_size=tracked_file.file_size,
            creation_time=tracked_file.creation_time,
            is_growing_at_queue_time=False,
            added_to_queue_at=datetime.now(),
        )

        # Setup mock to return the tracked file
        finalizer.file_repository.get_by_id.return_value = tracked_file

        file_size = 100
        await finalizer.finalize_success(job, file_size)

        # Verify state machine transition is called instead of job_queue
        finalizer.state_machine.transition.assert_called_once_with(
            file_id=tracked_file.id, new_status=FileStatus.COMPLETED
        )
        finalizer.event_bus.publish.assert_called()

    @pytest.mark.asyncio
    async def test_finalize_failure(self, finalizer):
        """Test failed job handling."""
        tracked_file = TrackedFile(
            file_path="/test/file.txt", file_size=100, status=FileStatus.READY
        )
        job = QueueJob(
            file_id=tracked_file.id,
            file_path=tracked_file.file_path,
            file_size=tracked_file.file_size,
            creation_time=tracked_file.creation_time,
            is_growing_at_queue_time=False,
            added_to_queue_at=datetime.now(),
        )
        error = Exception("Test error")

        # Setup mock to return the tracked file
        finalizer.file_repository.get_by_id.return_value = tracked_file

        await finalizer.finalize_failure(job, error)

        # Verify state machine transition is called instead of job_queue
        finalizer.state_machine.transition.assert_called_once_with(
            file_id=tracked_file.id, new_status=FileStatus.FAILED
        )

    @pytest.mark.asyncio
    async def test_finalize_max_retries(self, finalizer):
        """Test max retry attempts reached."""
        tracked_file = TrackedFile(
            file_path="/test/file.txt", file_size=100, status=FileStatus.READY
        )
        job = QueueJob(
            file_id=tracked_file.id,
            file_path=tracked_file.file_path,
            file_size=tracked_file.file_size,
            creation_time=tracked_file.creation_time,
            is_growing_at_queue_time=False,
            added_to_queue_at=datetime.now(),
        )

        # Setup mock to return the tracked file
        finalizer.file_repository.get_by_id.return_value = tracked_file

        await finalizer.finalize_max_retries(job)

        # Verify state machine transition is called instead of job_queue
        finalizer.state_machine.transition.assert_called_once_with(
            file_id=tracked_file.id, new_status=FileStatus.FAILED
        )

    def test_get_finalization_info(self, finalizer):
        """Test configuration info retrieval."""
        info = finalizer.get_finalization_info()

        assert info["max_retry_attempts"] == 3
        assert info["file_repository_available"] is True
        assert info["state_machine_available"] is True
