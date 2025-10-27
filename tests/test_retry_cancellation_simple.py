"""
Test retry task cancellation behavior in fail-and-rediscover strategy.
"""

import pytest
from unittest.mock import AsyncMock

from app.models import FileStatus
from app.services.state_manager import StateManager


class TestRetryTaskCancellationFailAndRediscover:
    """Test retry task cancellation with fail-and-rediscover strategy."""

    @pytest.mark.asyncio
    async def test_retry_task_cancelled_on_immediate_failure(self):
        """Test that retry tasks are cancelled when files fail immediately."""
        state_manager = StateManager(AsyncMock())

        # Create file and schedule retry
        file_path = "c:\\temp_input\\test_file.mxv"
        tracked_file = await state_manager.add_file(
            file_path=file_path, file_size=1000000
        )

        # Set to WAITING_FOR_SPACE and schedule retry
        await state_manager.update_file_status_by_id(
            file_id=tracked_file.id, status=FileStatus.WAITING_FOR_SPACE
        )

        await state_manager.schedule_retry(
            file_id=tracked_file.id,
            delay_seconds=300,
            reason="Test space retry",
            retry_type="space",
        )

        assert tracked_file.id in state_manager._retry_tasks, (
            "Retry task should be scheduled"
        )

        # Now fail the file immediately (simulating network error in fail-and-rediscover)
        await state_manager.update_file_status_by_id(
            file_id=tracked_file.id,
            status=FileStatus.FAILED,
            error_message="Network error - immediate failure",
        )

        # Verify retry task was cancelled
        assert tracked_file.id not in state_manager._retry_tasks, (
            "CRITICAL: Retry task was not cancelled when file failed immediately!"
        )
