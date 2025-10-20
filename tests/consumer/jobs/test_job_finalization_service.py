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


@pytest.fixture
def finalizer():
    """Simple finalizer for testing."""
    settings = MagicMock(max_retry_attempts=3)
    state_manager = AsyncMock()
    job_queue = AsyncMock()

    return JobFinalizationService(settings, state_manager, job_queue)


class TestJobFinalizationService:
    """Simple, focused tests for job finalization."""

    @pytest.mark.asyncio
    async def test_finalize_success(self, finalizer):
        """Test successful job completion."""
        tracked_file = TrackedFile(
            file_path="/test/file.txt", file_size=100, status=FileStatus.READY
        )
        job = QueueJob(tracked_file=tracked_file, added_to_queue_at=datetime.now())
        file_size = 1000

        await finalizer.finalize_success(job, file_size)

        finalizer.job_queue.mark_job_completed.assert_called_once_with(job)
        finalizer.state_manager.update_file_status_by_id.assert_called_once()

    @pytest.mark.asyncio
    async def test_finalize_failure(self, finalizer):
        """Test failed job handling."""
        tracked_file = TrackedFile(
            file_path="/test/file.txt", file_size=100, status=FileStatus.READY
        )
        job = QueueJob(tracked_file=tracked_file, added_to_queue_at=datetime.now())
        error = Exception("Test error")

        await finalizer.finalize_failure(job, error)

        finalizer.job_queue.mark_job_failed.assert_called_once_with(job, "Test error")
        finalizer.state_manager.update_file_status_by_id.assert_called_once()

    @pytest.mark.asyncio
    async def test_finalize_max_retries(self, finalizer):
        """Test max retry attempts reached."""
        tracked_file = TrackedFile(
            file_path="/test/file.txt", file_size=100, status=FileStatus.READY
        )
        job = QueueJob(tracked_file=tracked_file, added_to_queue_at=datetime.now())

        await finalizer.finalize_max_retries(job)

        finalizer.job_queue.mark_job_failed.assert_called_once_with(
            job, "Max retry attempts reached"
        )
        finalizer.state_manager.update_file_status_by_id.assert_called_once()

    def test_get_finalization_info(self, finalizer):
        """Test configuration info retrieval."""
        info = finalizer.get_finalization_info()

        assert info["max_retry_attempts"] == 3
        assert info["state_manager_available"] is True
        assert info["job_queue_available"] is True
