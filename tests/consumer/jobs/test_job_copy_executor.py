"""
Simple tests for JobCopyExecutor - follows 2:1 line ratio rule.

Tests copy execution and status management.
Max 85 lines for 172-line service.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
from datetime import datetime

from app.services.consumer.job_copy_executor import JobCopyExecutor
from app.models import FileStatus, TrackedFile
from app.services.consumer.job_models import PreparedFile, QueueJob
from app.services.copy.growing_copy import GrowingFileCopyStrategy
from app.core.file_repository import FileRepository
from app.core.events.event_bus import DomainEventBus
from app.services.consumer.job_error_classifier import JobErrorClassifier


@pytest.fixture
def executor():
    """Simple copy executor for testing."""
    settings = MagicMock()
    file_repository = AsyncMock(spec=FileRepository)
    copy_strategy = AsyncMock(spec=GrowingFileCopyStrategy)
    error_classifier = AsyncMock(spec=JobErrorClassifier)
    event_bus = AsyncMock(spec=DomainEventBus)

    return JobCopyExecutor(settings, file_repository, copy_strategy, error_classifier, event_bus)


@pytest.fixture
def prepared_file():
    """Simple prepared file for testing."""
    tracked_file = TrackedFile(
        file_path="/src/test.mxf", file_size=1000, status=FileStatus.READY
    )
    job = QueueJob(
        file_id=tracked_file.id,
        file_path=tracked_file.file_path,
        file_size=tracked_file.file_size,
        creation_time=tracked_file.creation_time,
        is_growing_at_queue_time=False,
        added_to_queue_at=datetime.now(),
    )
    return PreparedFile(
        job=job,
        strategy_name="GrowingFileCopyStrategy",
        initial_status=FileStatus.COPYING,
        destination_path=Path("/dst/test.mxf"),
    )


class TestJobCopyExecutor:
    """Simple, focused tests for copy execution."""

    @pytest.mark.asyncio
    async def test_initialize_copy_status(self, executor, prepared_file):
        """Test copy status initialization."""
        tracked_file = TrackedFile(
            id=prepared_file.job.file_id,
            file_path=prepared_file.job.file_path,
            file_size=prepared_file.job.file_size,
            status=FileStatus.COPYING,
            copy_progress=0.0,
            started_copying_at=datetime(2025, 10, 12, 12, 0, 0),
        )

        executor.file_repository.get_by_id.return_value = tracked_file

        await executor.initialize_copy_status(prepared_file)

        executor.file_repository.update.assert_called_once_with(tracked_file)

    @pytest.mark.asyncio
    async def test_execute_copy_success(self, executor, prepared_file):
        """Test successful copy execution."""
        executor.copy_strategy.copy_file.return_value = True

        with patch("pathlib.Path.exists", return_value=False):
            result = await executor.execute_copy(prepared_file)

        assert result is True
        executor.copy_strategy.copy_file.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_copy_failure(self, executor, prepared_file):
        """Test failed copy execution."""
        executor.copy_strategy.copy_file.return_value = False

        with patch("pathlib.Path.exists", return_value=False):
            result = await executor.execute_copy(prepared_file)

        assert result is False

    @pytest.mark.asyncio
    async def test_handle_copy_failure(self, executor, prepared_file):
        """Test copy failure handling."""
        tracked_file = TrackedFile(
            id=prepared_file.job.file_id,
            file_path=prepared_file.job.file_path,
            file_size=prepared_file.job.file_size,
            status=FileStatus.FAILED,
            error_message="Failed: Test error",
        )

        executor.file_repository.get_by_id.return_value = tracked_file

        executor.error_classifier.classify_copy_error.return_value = (FileStatus.FAILED, "Test error")

        await executor.handle_copy_failure(prepared_file, Exception("Test error"))

        # Verify that the file_repository.update method was called with the correct status
        updated_tracked_file = executor.file_repository.update.call_args[0][0]
        assert updated_tracked_file.status == FileStatus.FAILED
        assert updated_tracked_file.error_message == "Failed: Test error"

    def test_get_copy_executor_info(self, executor):
        """Test configuration info retrieval."""
        info = executor.get_copy_executor_info()

        assert info["copy_strategy"] == "GrowingFileCopyStrategy"
        assert info["file_repository_available"] is True
