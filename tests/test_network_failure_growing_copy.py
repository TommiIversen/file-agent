"""
Test network failure handling for GROWING_COPY operations
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.models import FileStatus, TrackedFile
from app.services.job_queue import JobQueueService
from app.services.state_manager import StateManager
from app.config import Settings

@pytest.mark.asyncio
class TestNetworkFailureHandling:
    
    @pytest.fixture
    def settings(self):
        return Settings(
            source_directory="c:\\temp_input",
            destination_directory="\\\\server\\share",
        )
    
    @pytest.fixture
    def mock_state_manager(self):
        mock = AsyncMock(spec=StateManager)
        return mock
    
    @pytest.fixture
    def job_queue(self, settings, mock_state_manager):
        return JobQueueService(
            settings=settings,
            state_manager=mock_state_manager,
            storage_monitor=None
        )
    
    async def test_fail_active_growing_operations_with_growing_copy_files(
        self, job_queue, mock_state_manager
    ):
        """Test that GROWING_COPY files are failed when network goes down"""
        # Arrange - create mock growing copy files
        growing_file1 = TrackedFile(
            id="growing1",
            file_path="c:\\temp_input\\file1.mxf",
            status=FileStatus.GROWING_COPY,
            file_size=1000000,
            bytes_copied=500000,
        )
        
        growing_file2 = TrackedFile(
            id="growing2", 
            file_path="c:\\temp_input\\file2.mxf",
            status=FileStatus.GROWING_COPY,
            file_size=2000000,
            bytes_copied=750000,
        )
        
        # Mock state manager to return these files
        mock_state_manager.get_files_by_status.side_effect = [
            [growing_file1, growing_file2],  # GROWING_COPY files
            []  # COPYING files  
        ]
        
        # Act
        failed_count = await job_queue._fail_active_growing_operations()
        
        # Assert
        assert failed_count == 2
        
        # Verify that update_file_status_by_id was called for each file
        expected_calls = [
            (growing_file1.id, FileStatus.FAILED, "Network interruption during growing copy - will rediscover when network returns"),
            (growing_file2.id, FileStatus.FAILED, "Network interruption during growing copy - will rediscover when network returns"),
        ]
        
        actual_calls = mock_state_manager.update_file_status_by_id.call_args_list
        assert len(actual_calls) == 2
        
        for i, call in enumerate(actual_calls):
            args, kwargs = call
            assert kwargs["file_id"] == expected_calls[i][0]
            assert kwargs["status"] == expected_calls[i][1]
            assert kwargs["error_message"] == expected_calls[i][2]
    
    async def test_fail_active_growing_operations_with_copying_files(
        self, job_queue, mock_state_manager
    ):
        """Test that COPYING files with bytes_copied are failed when network goes down"""
        # Arrange - create mock copying files that were likely growing copies
        copying_file_with_progress = TrackedFile(
            id="copying1",
            file_path="c:\\temp_input\\file3.mxf", 
            status=FileStatus.COPYING,
            file_size=3000000,
            bytes_copied=1500000,  # Has progress, likely was growing
        )
        
        copying_file_fresh = TrackedFile(
            id="copying2",
            file_path="c:\\temp_input\\file4.mxv",
            status=FileStatus.COPYING,
            file_size=4000000,
            bytes_copied=0,  # No progress, likely fresh copy
        )
        
        # Mock state manager
        mock_state_manager.get_files_by_status.side_effect = [
            [],  # No GROWING_COPY files
            [copying_file_with_progress, copying_file_fresh]  # COPYING files
        ]
        
        # Act
        failed_count = await job_queue._fail_active_growing_operations()
        
        # Assert - only the file with progress should be failed
        assert failed_count == 1
        
        # Verify only the file with bytes_copied > 0 was updated
        mock_state_manager.update_file_status_by_id.assert_called_once_with(
            file_id="copying1",
            status=FileStatus.FAILED,
            error_message="Network interruption during copy operation - will rediscover when network returns",
        )
    
    async def test_fail_active_growing_operations_no_files(
        self, job_queue, mock_state_manager
    ):
        """Test that no failures occur when no growing/copying files exist"""
        # Arrange - no files
        mock_state_manager.get_files_by_status.side_effect = [
            [],  # No GROWING_COPY files
            []   # No COPYING files
        ]
        
        # Act
        failed_count = await job_queue._fail_active_growing_operations()
        
        # Assert
        assert failed_count == 0
        mock_state_manager.update_file_status_by_id.assert_not_called()
    
    async def test_handle_destination_unavailable_calls_fail_operations(
        self, job_queue, mock_state_manager
    ):
        """Test that handle_destination_unavailable calls the fail operations method"""
        # Arrange
        mock_state_manager.get_files_by_status.side_effect = [[], []]
        
        # Act
        await job_queue.handle_destination_unavailable()
        
        # Assert - verify both status calls were made (GROWING_COPY and COPYING)
        expected_calls = [
            ((FileStatus.GROWING_COPY,), {}),
            ((FileStatus.COPYING,), {}),
        ]
        
        actual_calls = mock_state_manager.get_files_by_status.call_args_list
        assert actual_calls == expected_calls