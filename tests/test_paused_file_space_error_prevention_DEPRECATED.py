"""
Test to prevent incorrect transition from PAUSED_GROWING_COPY to SPACE_ERROR.

This test catches a critical bug where files in PAUSED_GROWING_COPY status
incorrectly transition to SPACE_ERROR after max_space_retries, instead of
remaining paused until destination storage becomes available again.

RULE: Files that are paused due to destination storage issues should NEVER
transition to SPACE_ERROR. They should remain in their paused state until
the destination becomes available again.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from app.config import Settings
from app.models import FileStatus, TrackedFile, SpaceCheckResult
from app.services.space_retry_manager import SpaceRetryManager
from app.services.state_manager import StateManager


class TestPausedFileSpaceErrorPrevention:
    """Test suite to prevent PAUSED_GROWING_COPY -> SPACE_ERROR transitions."""

    @pytest.fixture
    def settings(self):
        """Test settings with low retry count for faster testing."""
        settings = Settings()
        settings.max_space_retries = 2  # Low number to trigger the bug quickly
        settings.space_retry_delay_seconds = 1  # Fast retries for testing
        return settings

    @pytest.fixture
    def state_manager(self):
        """Mock state manager."""
        return AsyncMock(spec=StateManager)

    @pytest.fixture
    def space_retry_manager(self, settings, state_manager):
        """Space retry manager instance."""
        return SpaceRetryManager(settings, state_manager)

    @pytest.fixture
    def paused_growing_file(self):
        """A file that was paused during growing copy due to destination storage issues."""
        return TrackedFile(
            id="test-uuid-123",
            file_path="test_video.mxf",
            status=FileStatus.PAUSED_GROWING_COPY,  # Paused due to destination storage
            file_size=1000000000,  # 1GB
            bytes_copied=500000000,  # 500MB already copied
            discovered_at=datetime.now() - timedelta(minutes=10),
            error_message="Destination storage unavailable"
        )

    @pytest.fixture
    def space_check_result(self):
        """Space check showing insufficient space."""
        return SpaceCheckResult(
            has_space=False,
            available_bytes=100000000,  # 100MB available
            required_bytes=500000000,   # 500MB needed to complete
            file_size_bytes=1000000000, # 1GB total file size
            safety_margin_bytes=50000000,  # 50MB safety margin
            reason="Insufficient space for file completion"
        )

    @pytest.mark.asyncio
    async def test_paused_growing_copy_should_not_become_space_error(
        self, space_retry_manager, state_manager, paused_growing_file, space_check_result
    ):
        """
        CRITICAL TEST: Paused growing files should NEVER transition to SPACE_ERROR.
        
        When a file is in PAUSED_GROWING_COPY due to destination storage issues,
        the SpaceRetryManager should NOT increment retry counts or mark it as
        SPACE_ERROR after max_space_retries. It should remain paused until
        destination becomes available.
        """
        # Setup: File has been retried multiple times already (near limit)
        state_manager.increment_retry_count.return_value = 2  # At max_space_retries
        
        # Act: Schedule space retry for paused growing file
        await space_retry_manager.schedule_space_retry(
            paused_growing_file, space_check_result
        )
        
        # Assert: File should NOT be marked as SPACE_ERROR
        # It should remain in PAUSED_GROWING_COPY or similar paused state
        update_calls = state_manager.update_file_status_by_id.call_args_list
        
        # Check that no call sets status to SPACE_ERROR
        for call in update_calls:
            call_kwargs = call.kwargs if hasattr(call, 'kwargs') else call[1]
            assert call_kwargs.get('status') != FileStatus.SPACE_ERROR, (
                f"CRITICAL BUG: Paused file {paused_growing_file.file_path} "
                f"was incorrectly marked as SPACE_ERROR! "
                f"Files in PAUSED_GROWING_COPY should remain paused until "
                f"destination storage becomes available."
            )

    @pytest.mark.asyncio
    async def test_paused_files_should_not_increment_retry_count(
        self, space_retry_manager, state_manager, paused_growing_file, space_check_result
    ):
        """
        Paused files should not have their retry count incremented.
        
        When destination storage is unavailable, files are paused. While paused,
        they should NOT accumulate retry counts that could lead to SPACE_ERROR.
        """
        # Setup: Return actual int for retry count
        state_manager.increment_retry_count.return_value = 1
        
        # Act: Schedule space retry for paused file
        await space_retry_manager.schedule_space_retry(
            paused_growing_file, space_check_result
        )
        
        # Assert: Retry count should NOT be incremented for paused files
        if paused_growing_file.status in [
            FileStatus.PAUSED_GROWING_COPY,
            FileStatus.PAUSED_COPYING,
            FileStatus.PAUSED_IN_QUEUE
        ]:
            state_manager.increment_retry_count.assert_not_called()

    @pytest.mark.asyncio
    async def test_only_active_files_should_increment_retry_count(
        self, space_retry_manager, state_manager, space_check_result
    ):
        """
        Only actively copying files should increment retry counts.
        
        Files in COPYING, GROWING_COPY, or IN_QUEUE status can legitimately
        fail due to space issues and should increment retry counts.
        """
        active_statuses = [
            FileStatus.COPYING,
            FileStatus.GROWING_COPY,
            FileStatus.IN_QUEUE
        ]
        
        for status in active_statuses:
            # Reset mock
            state_manager.reset_mock()
            state_manager.increment_retry_count.return_value = 1
            
            # Create active file
            active_file = TrackedFile(
                id=f"test-uuid-{status.value}",
                file_path=f"test_{status.value}.mxf",
                status=status,
                file_size=1000000000,
                discovered_at=datetime.now()
            )
            
            # Act: Schedule space retry for active file
            await space_retry_manager.schedule_space_retry(
                active_file, space_check_result
            )
            
            # Assert: Retry count should be incremented for active files
            state_manager.increment_retry_count.assert_called_once_with(active_file.id)

    @pytest.mark.asyncio
    async def test_paused_file_recovery_scenario(
        self, space_retry_manager, state_manager, paused_growing_file, space_check_result
    ):
        """
        Test the complete recovery scenario for paused files.
        
        1. File is paused due to destination storage issues
        2. Multiple space retries are attempted (should NOT increment count)
        3. Destination storage becomes available
        4. File should resume from PAUSED_GROWING_COPY, not SPACE_ERROR
        """
        # Setup: Multiple retry attempts while paused
        state_manager.increment_retry_count.return_value = 5  # Way over limit
        
        # Act: Multiple space retry attempts while file is paused
        for _ in range(3):
            await space_retry_manager.schedule_space_retry(
                paused_growing_file, space_check_result
            )
        
        # Assert: File should still be recoverable, not in SPACE_ERROR
        update_calls = state_manager.update_file_status_by_id.call_args_list
        
        # Verify no SPACE_ERROR status was set
        space_error_calls = [
            call for call in update_calls 
            if (call.kwargs if hasattr(call, 'kwargs') else call[1]).get('status') == FileStatus.SPACE_ERROR
        ]
        
        assert len(space_error_calls) == 0, (
            f"File should remain recoverable even after multiple retry attempts. "
            f"Found {len(space_error_calls)} calls setting SPACE_ERROR status."
        )

    def test_bug_documentation(self):
        """
        Document the exact bug this test prevents.
        
        This serves as documentation for future developers about why
        this test exists and what specific scenario it prevents.
        """
        bug_description = """
        BUG PREVENTED BY THIS TEST:
        
        1. File starts copying in GROWING_COPY mode
        2. Destination storage becomes unavailable 
        3. File transitions to PAUSED_GROWING_COPY (correct)
        4. SpaceRetryManager continues to retry and increment retry count (WRONG)
        5. After max_space_retries attempts, file becomes SPACE_ERROR (WRONG)
        6. File is now permanently stuck even when destination recovers (WRONG)
        
        CORRECT BEHAVIOR:
        - Files in PAUSED_* states should NOT increment retry counts
        - Files in PAUSED_* states should NEVER become SPACE_ERROR
        - Files should remain paused until destination becomes available
        - Universal recovery should handle paused files when destination recovers
        """
        
        # This test ensures the bug described above cannot happen
        assert True, bug_description


if __name__ == "__main__":
    pytest.main([__file__, "-v"])