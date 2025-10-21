"""
Test that scheduled retry tasks are cancelled when files are paused.

This test ensures that when a file is paused due to network interruption,
any previously scheduled retry tasks are cancelled to prevent the file
from being reactivated while it should remain paused.
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

from app.models import TrackedFile, FileStatus
from app.services.state_manager import StateManager


class TestRetryTaskCancellation:
    """Test that retry tasks are properly cancelled when files are paused."""

    @pytest.mark.asyncio
    async def test_retry_task_cancelled_when_file_paused(self):
        """Test that scheduled retry tasks are cancelled when file transitions to paused state."""
        state_manager = StateManager(AsyncMock())
        
        # Create a file in WAITING_FOR_SPACE status (typical before retry scheduling)
        file_path = "c:\\temp_input\\test_file.mxf"
        tracked_file = await state_manager.add_file(
            file_path=file_path,
            file_size=1000000
        )
        
        # Update to WAITING_FOR_SPACE status
        await state_manager.update_file_status_by_id(
            file_id=tracked_file.id,
            status=FileStatus.WAITING_FOR_SPACE
        )
        
        # Schedule a retry (simulating space retry manager)
        retry_scheduled = await state_manager.schedule_retry(
            file_id=tracked_file.id,
            delay_seconds=300,  # 5 minutes
            reason="Destination not accessible",
            retry_type="space"
        )
        
        assert retry_scheduled is True, "Retry should be scheduled for WAITING_FOR_SPACE file"
        
        # Verify retry task exists
        assert tracked_file.id in state_manager._retry_tasks, "Retry task should be scheduled"
        retry_task = state_manager._retry_tasks[tracked_file.id]
        assert not retry_task.done(), "Retry task should be running"
        
        # Now pause the file (simulating network interruption)
        await state_manager.update_file_status_by_id(
            file_id=tracked_file.id,
            status=FileStatus.PAUSED_GROWING_COPY
        )
        
        # Verify retry task was cancelled
        assert tracked_file.id not in state_manager._retry_tasks, (
            "CRITICAL BUG: Retry task was not cancelled when file was paused! "
            "This will cause paused files to be reactivated by scheduled retries."
        )
        
        # Verify the retry task was actually cancelled
        assert retry_task.cancelled(), (
            "CRITICAL BUG: Retry task was not properly cancelled when file was paused!"
        )

    @pytest.mark.asyncio
    async def test_no_retry_scheduled_for_paused_files(self):
        """Test that retry scheduling is rejected for files that are already paused."""
        state_manager = StateManager(AsyncMock())
        
        # Create a file and immediately pause it
        file_path = "c:\\temp_input\\paused_file.mxv"
        tracked_file = await state_manager.add_file(
            file_path=file_path,
            file_size=1000000
        )
        
        # Set to paused state
        await state_manager.update_file_status_by_id(
            file_id=tracked_file.id,
            status=FileStatus.PAUSED_GROWING_COPY
        )
        
        # Try to schedule a retry for paused file
        retry_scheduled = await state_manager.schedule_retry(
            file_id=tracked_file.id,
            delay_seconds=300,
            reason="Test retry on paused file",
            retry_type="space"
        )
        
        # Should be rejected
        assert retry_scheduled is False, (
            "CRITICAL BUG: Retry scheduling should be rejected for paused files! "
            "Paused files must wait for network recovery, not scheduled retries."
        )
        
        # Verify no retry task was created
        assert tracked_file.id not in state_manager._retry_tasks, (
            "Retry task should not be created for paused files"
        )

    @pytest.mark.asyncio
    async def test_retry_task_cancellation_fail_and_rediscover(self):
        """Test that FAILED status properly cancels retry tasks in fail-and-rediscover strategy."""
        state_manager = StateManager(AsyncMock())
        
        # In fail-and-rediscover strategy, network errors cause immediate FAILED status
        failed_status = FileStatus.FAILED
        
        # Create file with retry scheduled
        file_path = f"c:\\temp_input\\test_failed.mxv"
        tracked_file = await state_manager.add_file(
            file_path=file_path,
            file_size=1000000
        )
        
        # Set to WAITING_FOR_SPACE and schedule retry
        await state_manager.update_file_status_by_id(
            file_id=tracked_file.id,
            status=FileStatus.WAITING_FOR_SPACE
        )
        
        await state_manager.schedule_retry(
            file_id=tracked_file.id,
            delay_seconds=300,
            reason="Test retry for failed network error",
            retry_type="space"
        )
        
        # Verify retry task exists
        assert tracked_file.id in state_manager._retry_tasks
        
        # Fail the file (simulating network error in fail-and-rediscover)
        await state_manager.update_file_status_by_id(
            file_id=tracked_file.id,
            status=failed_status,
            error_message="Network error - immediate failure"
        )
        
        # In fail-and-rediscover strategy, retry tasks should be cancelled
        # when files transition to FAILED due to network errors
        assert tracked_file.id not in state_manager._retry_tasks, (
            "CRITICAL: Retry task was not cancelled when file failed immediately!"
        )

    @pytest.mark.asyncio
    async def test_retry_task_respects_paused_state_during_execution(self):
        """Test that retry task checks for paused state before reactivating file."""
        state_manager = StateManager(AsyncMock())
        
        # Create file and schedule retry with very short delay for testing
        file_path = "c:\\temp_input\\test_file.mxf"
        tracked_file = await state_manager.add_file(
            file_path=file_path,
            file_size=1000000
        )
        
        await state_manager.update_file_status_by_id(
            file_id=tracked_file.id,
            status=FileStatus.WAITING_FOR_SPACE
        )
        
        # Schedule retry with short delay
        await state_manager.schedule_retry(
            file_id=tracked_file.id,
            delay_seconds=0.1,  # 100ms for fast test
            reason="Test retry execution",
            retry_type="space"
        )
        
        # Immediately pause the file (simulating race condition)
        await state_manager.update_file_status_by_id(
            file_id=tracked_file.id,
            status=FileStatus.PAUSED_GROWING_COPY
        )
        
        # Wait for retry task to execute
        await asyncio.sleep(0.2)
        
        # Verify file remains paused (not reactivated by retry)
        current_file = state_manager._files_by_id.get(tracked_file.id)
        assert current_file.status == FileStatus.PAUSED_GROWING_COPY, (
            "CRITICAL BUG: Retry task reactivated a paused file! "
            "Retry tasks must respect paused state during execution."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])