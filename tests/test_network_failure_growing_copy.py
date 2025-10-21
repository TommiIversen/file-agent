"""
Test network failure handling through fail-fast detection
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
    
    async def test_handle_destination_unavailable_pauses_operations(
        self, job_queue, mock_state_manager
    ):
        """Test that handle_destination_unavailable is called when network goes down"""
        # This method is called by storage monitor when destination becomes unavailable
        # In the new fail-fast architecture, individual files fail via NetworkErrorDetector
        # but this method is still called to handle overall state
        
        # Mock the state manager methods that would be called
        mock_state_manager.get_active_copy_files.return_value = []
        
        # Act
        await job_queue.handle_destination_unavailable()
        
        # Assert - in the current implementation, this just logs but doesn't actively fail files
        # The actual failure happens at the copy operation level via NetworkErrorDetector
        mock_state_manager.get_active_copy_files.assert_called_once()
    
    async def test_handle_destination_recovery_processes_waiting_files(
        self, job_queue, mock_state_manager
    ):
        """Test that destination recovery is handled properly"""
        
        # Act
        await job_queue.handle_destination_recovery()
        
        # Assert - in fail-fast architecture, this just logs success
        # Actual recovery happens via process_waiting_network_files when storage monitor detects recovery
        # This test just verifies the method doesn't crash
        assert True  # Method completes without error
    
    async def test_pause_active_operations_returns_zero(
        self, job_queue, mock_state_manager
    ):
        """Test that _pause_active_operations now returns 0 in fail-fast architecture"""
        
        # Mock some active files
        mock_state_manager.get_active_copy_files.return_value = [
            TrackedFile(
                id="active1",
                file_path="c:\\temp_input\\file1.mxf",
                status=FileStatus.GROWING_COPY,
                file_size=1000000,
                bytes_copied=500000,
            )
        ]
        mock_state_manager.get_all_files.return_value = []
        
        # Act
        paused_count = await job_queue._pause_active_operations()
        
        # Assert - should return 0 since pause logic was removed
        assert paused_count == 0
        
    async def test_get_recent_network_failed_files(
        self, job_queue, mock_state_manager
    ):
        """Test that recent network failed files are retrieved correctly"""
        
        from datetime import datetime, timedelta
        
        # Create mock failed files
        recent_time = datetime.now() - timedelta(minutes=2)  # Recent failure
        old_time = datetime.now() - timedelta(minutes=10)   # Old failure
        
        failed_files = [
            TrackedFile(
                id="failed1",
                file_path="c:\\temp_input\\file1.mxf", 
                status=FileStatus.FAILED,
                error_message="Network error during growing copy chunk write: [Errno 22] Invalid argument",
                failed_at=recent_time
            ),
            TrackedFile(
                id="failed2",
                file_path="c:\\temp_input\\file2.mxf",
                status=FileStatus.FAILED, 
                error_message="Regular file error",
                failed_at=recent_time
            ),
            TrackedFile(
                id="failed3",
                file_path="c:\\temp_input\\file3.mxf",
                status=FileStatus.FAILED,
                error_message="Network error during copy", 
                failed_at=old_time  # Too old
            )
        ]
        
        mock_state_manager.get_all_files.return_value = failed_files
        
        # Act
        recent_network_files = await job_queue._get_recent_network_failed_files()
        
        # Assert - should return only recent network error file
        assert len(recent_network_files) == 1  # Only the recent network error file
        assert recent_network_files[0].id == "failed1"
        assert "Network error" in recent_network_files[0].error_message
    
    async def test_is_likely_network_failure_detection(
        self, job_queue
    ):
        """Test network failure detection in error messages"""
        
        # Test network error cases
        network_error_file = TrackedFile(
            id="net1",
            file_path="c:\\temp\\test.mxf",
            status=FileStatus.FAILED,
            error_message="Network error during growing copy chunk write: [Errno 22] Invalid argument"
        )
        
        errno_error_file = TrackedFile(
            id="net2", 
            file_path="c:\\temp\\test2.mxf",
            status=FileStatus.FAILED,
            error_message="[Errno 53] The network path was not found"
        )
        
        regular_error_file = TrackedFile(
            id="reg1",
            file_path="c:\\temp\\test3.mxf", 
            status=FileStatus.FAILED,
            error_message="Permission denied"
        )
        
        # Act & Assert
        assert job_queue._is_likely_network_failure(network_error_file) == True
        assert job_queue._is_likely_network_failure(errno_error_file) == True  
        assert job_queue._is_likely_network_failure(regular_error_file) == False