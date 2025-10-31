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
from app.services.consumer.job_models import PreparedFile
from app.services.copy.growing_copy import GrowingFileCopyStrategy


@pytest.fixture
def executor():
    """Simple copy executor for testing."""
    settings = MagicMock()
    state_manager = AsyncMock()
    copy_strategy = AsyncMock(spec=GrowingFileCopyStrategy)

    return JobCopyExecutor(settings, state_manager, copy_strategy)


@pytest.fixture
def prepared_file():
    """Simple prepared file for testing."""
    tracked_file = TrackedFile(
        file_path="/src/test.mxf", file_size=1000, status=FileStatus.READY
    )
    return PreparedFile(
        tracked_file=tracked_file,
        strategy_name="GrowingFileCopyStrategy",
        initial_status=FileStatus.COPYING,
        destination_path=Path("/dst/test.mxf"),
    )


class TestJobCopyExecutor:
    """Simple, focused tests for copy execution."""

    @pytest.mark.asyncio
    async def test_initialize_copy_status(self, executor, prepared_file):
        """Test copy status initialization."""
        with patch("app.services.consumer.job_copy_executor.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 10, 12, 12, 0, 0)

            await executor.initialize_copy_status(prepared_file)

        executor.state_manager.update_file_status_by_id.assert_called_once_with(
            prepared_file.tracked_file.id,
            FileStatus.COPYING,
            copy_progress=0.0,
            started_copying_at=datetime(2025, 10, 12, 12, 0, 0),
        )

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
        await executor.handle_copy_failure(prepared_file, "Test error")

        executor.state_manager.update_file_status_by_id.assert_called_once_with(
            prepared_file.tracked_file.id,
            FileStatus.FAILED,
            copy_progress=0.0,
            bytes_copied=0,
            error_message="Failed: Copy operation failed",
        )

    def test_get_copy_executor_info(self, executor):
        """Test configuration info retrieval."""
        info = executor.get_copy_executor_info()

        assert info["copy_strategy"] == "GrowingFileCopyStrategy"
        assert info["state_manager_available"] is True
