"""
Tests for Job Processor Service.

Comprehensive test suite covering:
- Job processing workflow
- Space checking integration
- Job preparation and validation
- File status management
- Job finalization (success/failure)
- Error handling and edge cases
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from pathlib import Path

from app.config import Settings
from app.models import FileStatus, SpaceCheckResult, TrackedFile
from app.services.consumer.job_processor import JobProcessor, ProcessResult, PreparedFile
from app.services.state_manager import StateManager
from app.services.job_queue import JobQueueService
from app.services.copy_strategies import FileCopyStrategyFactory


class TestJobProcessorBasics:
    """Test basic JobProcessor functionality."""
    
    @pytest.fixture
    def settings(self):
        """Create test settings."""
        return Settings(
            source_directory="/test/source",
            destination_directory="/test/dest",
            enable_pre_copy_space_check=True,
            max_retry_attempts=3
        )
    
    @pytest.fixture
    def mock_state_manager(self):
        """Create mock StateManager."""
        mock = AsyncMock(spec=StateManager)
        return mock
    
    @pytest.fixture
    def mock_job_queue(self):
        """Create mock JobQueueService."""
        mock = AsyncMock(spec=JobQueueService)
        return mock
    
    @pytest.fixture
    def mock_copy_strategy_factory(self):
        """Create mock FileCopyStrategyFactory."""
        mock = Mock(spec=FileCopyStrategyFactory)
        # Create a mock strategy
        mock_strategy = Mock()
        mock_strategy.__class__.__name__ = "NormalFileCopyStrategy"
        mock.get_strategy.return_value = mock_strategy
        mock.get_available_strategies.return_value = {"normal": mock_strategy}
        return mock
    
    @pytest.fixture
    def mock_space_checker(self):
        """Create mock space checker."""
        mock = Mock()
        mock.check_space_for_file.return_value = SpaceCheckResult(
            has_space=True, 
            reason="OK",
            available_bytes=10000000000,  # 10GB
            required_bytes=1000,          # 1KB
            file_size_bytes=1000,
            safety_margin_bytes=0
        )
        return mock
    
    @pytest.fixture
    def mock_space_retry_manager(self):
        """Create mock space retry manager."""
        mock = AsyncMock()
        return mock
    
    @pytest.fixture
    def processor(self, settings, mock_state_manager, mock_job_queue, mock_copy_strategy_factory):
        """Create JobProcessor instance."""
        return JobProcessor(
            settings=settings,
            state_manager=mock_state_manager,
            job_queue=mock_job_queue,
            copy_strategy_factory=mock_copy_strategy_factory
        )
    
    @pytest.fixture
    def processor_with_space_checking(
        self, settings, mock_state_manager, mock_job_queue, 
        mock_copy_strategy_factory, mock_space_checker, mock_space_retry_manager
    ):
        """Create JobProcessor with space checking enabled."""
        return JobProcessor(
            settings=settings,
            state_manager=mock_state_manager,
            job_queue=mock_job_queue,
            copy_strategy_factory=mock_copy_strategy_factory,
            space_checker=mock_space_checker,
            space_retry_manager=mock_space_retry_manager
        )
    
    def test_initialization(self, processor, settings):
        """Test JobProcessor initialization."""
        assert processor.settings == settings
        assert processor.state_manager is not None
        assert processor.job_queue is not None
        assert processor.copy_strategy_factory is not None
        assert processor.space_checker is None
        assert processor.space_retry_manager is None
    
    def test_initialization_with_space_checking(self, processor_with_space_checking):
        """Test initialization with space checking components."""
        assert processor_with_space_checking.space_checker is not None
        assert processor_with_space_checking.space_retry_manager is not None
    
    def test_get_processor_info(self, processor):
        """Test processor configuration info."""
        info = processor.get_processor_info()
        
        expected_info = {
            "space_checking_enabled": False,  # No space checker
            "max_retry_attempts": 3,
            "space_retry_manager_available": False,
            "copy_strategies_available": 1
        }
        
        assert info == expected_info
    
    def test_get_processor_info_with_space_checking(self, processor_with_space_checking):
        """Test processor info with space checking enabled."""
        info = processor_with_space_checking.get_processor_info()
        
        assert info["space_checking_enabled"] is True
        assert info["space_retry_manager_available"] is True
    
    def test_should_check_space_disabled(self, processor):
        """Test space checking when disabled."""
        assert processor._should_check_space() is False
    
    def test_should_check_space_enabled(self, processor_with_space_checking):
        """Test space checking when enabled."""
        assert processor_with_space_checking._should_check_space() is True


class TestProcessResultAndPreparedFile:
    """Test ProcessResult and PreparedFile dataclasses."""
    
    def test_process_result_success(self):
        """Test ProcessResult for successful processing."""
        result = ProcessResult(success=True, file_path="/test/file.txt")
        
        assert result.success is True
        assert result.file_path == "/test/file.txt"
        assert result.error_message is None
        assert result.retry_scheduled is False
        assert result.space_shortage is False
        
        summary = result.get_summary()
        assert "successfully" in summary.lower()
        assert "file.txt" in summary
    
    def test_process_result_failure(self):
        """Test ProcessResult for failed processing."""
        result = ProcessResult(
            success=False, 
            file_path="/test/file.txt",
            error_message="Test error"
        )
        
        assert result.success is False
        assert result.error_message == "Test error"
        
        summary = result.get_summary()
        assert "failed" in summary.lower()
        assert "Test error" in summary
    
    def test_process_result_space_shortage(self):
        """Test ProcessResult for space shortage."""
        result = ProcessResult(
            success=False,
            file_path="/test/file.txt",
            error_message="Insufficient space",
            retry_scheduled=True,
            space_shortage=True
        )
        
        assert result.space_shortage is True
        assert result.retry_scheduled is True
        
        summary = result.get_summary()
        assert "space shortage" in summary.lower()
        assert "retry scheduled" in summary.lower()
    
    def test_prepared_file_creation(self):
        """Test PreparedFile creation."""
        tracked_file = TrackedFile(
            file_path="/test/file.txt",
            file_size=1000,
            status=FileStatus.READY
        )
        
        prepared = PreparedFile(
            tracked_file=tracked_file,
            strategy_name="NormalFileCopyStrategy",
            initial_status=FileStatus.COPYING,
            destination_path=Path("/dest/file.txt")
        )
        
        assert prepared.tracked_file == tracked_file
        assert prepared.strategy_name == "NormalFileCopyStrategy"
        assert prepared.initial_status == FileStatus.COPYING
        assert prepared.destination_path == Path("/dest/file.txt")


class TestJobProcessing:
    """Test core job processing functionality."""
    
    @pytest.fixture
    def settings(self):
        """Create test settings."""
        return Settings(
            source_directory="/test/source",
            destination_directory="/test/dest",
            enable_pre_copy_space_check=True,
            max_retry_attempts=3
        )
    
    @pytest.fixture
    def mock_state_manager(self):
        """Create mock StateManager."""
        mock = AsyncMock(spec=StateManager)
        return mock
    
    @pytest.fixture
    def mock_job_queue(self):
        """Create mock JobQueueService."""
        mock = AsyncMock(spec=JobQueueService)
        return mock
    
    @pytest.fixture
    def mock_copy_strategy_factory(self):
        """Create mock FileCopyStrategyFactory."""
        mock = Mock(spec=FileCopyStrategyFactory)
        # Create a mock strategy
        mock_strategy = Mock()
        mock_strategy.__class__.__name__ = "NormalFileCopyStrategy"
        mock.get_strategy.return_value = mock_strategy
        mock.get_available_strategies.return_value = {"normal": mock_strategy}
        return mock
    
    @pytest.fixture
    def mock_space_checker(self):
        """Create mock space checker."""
        mock = Mock()
        mock.check_space_for_file.return_value = SpaceCheckResult(
            has_space=True, 
            reason="OK",
            available_bytes=10000000000,  # 10GB
            required_bytes=1000,          # 1KB
            file_size_bytes=1000,
            safety_margin_bytes=0
        )
        return mock
    
    @pytest.fixture
    def mock_space_retry_manager(self):
        """Create mock space retry manager."""
        mock = AsyncMock()
        return mock
    
    @pytest.fixture
    def processor(self, settings, mock_state_manager, mock_job_queue, mock_copy_strategy_factory):
        """Create JobProcessor instance."""
        return JobProcessor(
            settings=settings,
            state_manager=mock_state_manager,
            job_queue=mock_job_queue,
            copy_strategy_factory=mock_copy_strategy_factory
        )
    
    @pytest.fixture
    def processor_with_space_checking(
        self, settings, mock_state_manager, mock_job_queue, 
        mock_copy_strategy_factory, mock_space_checker, mock_space_retry_manager
    ):
        """Create JobProcessor with space checking enabled."""
        return JobProcessor(
            settings=settings,
            state_manager=mock_state_manager,
            job_queue=mock_job_queue,
            copy_strategy_factory=mock_copy_strategy_factory,
            space_checker=mock_space_checker,
            space_retry_manager=mock_space_retry_manager
        )
    
    @pytest.fixture
    def sample_job(self):
        """Create a sample job for testing."""
        return {
            "file_path": "/test/source/sample.txt",
            "file_size": 1000
        }
    
    @pytest.fixture
    def sample_tracked_file(self):
        """Create a sample tracked file."""
        return TrackedFile(
            file_path="/test/source/sample.txt",
            file_size=1000,
            status=FileStatus.READY
        )
    
    @pytest.mark.asyncio
    async def test_process_job_success_without_space_checking(
        self, processor, sample_job, sample_tracked_file, mock_state_manager
    ):
        """Test successful job processing without space checking."""
        # Setup mocks
        mock_state_manager.get_file.return_value = sample_tracked_file
        mock_state_manager.update_file_status.return_value = None
        
        # Process job
        result = await processor.process_job(sample_job)
        
        # Verify result
        assert result.success is True
        assert result.file_path == sample_job["file_path"]
        assert result.error_message is None
        
        # Verify state manager calls
        mock_state_manager.get_file.assert_called_once_with(sample_job["file_path"])
        mock_state_manager.update_file_status.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_process_job_success_with_space_checking(
        self, processor_with_space_checking, sample_job, sample_tracked_file, 
        mock_state_manager, mock_space_checker
    ):
        """Test successful job processing with space checking."""
        # Setup mocks
        mock_state_manager.get_file.return_value = sample_tracked_file
        mock_state_manager.update_file_status.return_value = None
        mock_space_checker.check_space_for_file.return_value = SpaceCheckResult(
            has_space=True, 
            reason="OK",
            available_bytes=10000000000,
            required_bytes=1000,
            file_size_bytes=1000,
            safety_margin_bytes=0
        )
        
        # Process job
        result = await processor_with_space_checking.process_job(sample_job)
        
        # Verify result
        assert result.success is True
        
        # Verify space checking was called
        mock_space_checker.check_space_for_file.assert_called_once_with(1000)
    
    @pytest.mark.asyncio
    async def test_process_job_file_not_found(
        self, processor, sample_job, mock_state_manager
    ):
        """Test job processing when file not found in state manager."""
        # Setup mock to return None (file not found)
        mock_state_manager.get_file.return_value = None
        
        # Process job
        result = await processor.process_job(sample_job)
        
        # Verify result
        assert result.success is False
        assert "not found in state manager" in result.error_message
    
    @pytest.mark.asyncio
    async def test_process_job_space_shortage_with_retry(
        self, processor_with_space_checking, sample_job, 
        mock_space_checker, mock_space_retry_manager
    ):
        """Test job processing with space shortage and retry scheduling."""
        # Setup space shortage
        space_check = SpaceCheckResult(
            has_space=False, 
            reason="Insufficient space",
            available_bytes=500,
            required_bytes=1000,
            file_size_bytes=1000,
            safety_margin_bytes=0
        )
        mock_space_checker.check_space_for_file.return_value = space_check
        mock_space_retry_manager.schedule_space_retry.return_value = None
        
        # Process job
        result = await processor_with_space_checking.process_job(sample_job)
        
        # Verify result
        assert result.success is False
        assert result.space_shortage is True
        assert result.retry_scheduled is True
        assert "Insufficient space" in result.error_message
        
        # Verify retry was scheduled
        mock_space_retry_manager.schedule_space_retry.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_process_job_unexpected_error(
        self, processor, sample_job, mock_state_manager
    ):
        """Test job processing with unexpected error."""
        # Setup mock to raise exception
        mock_state_manager.get_file.side_effect = Exception("Database error")
        
        # Process job
        result = await processor.process_job(sample_job)
        
        # Verify result
        assert result.success is False
        assert "Unexpected error" in result.error_message
        assert "Database error" in result.error_message


class TestSpaceChecking:
    """Test space checking functionality."""
    
    @pytest.fixture
    def sample_job(self):
        """Create a sample job for testing."""
        return {
            "file_path": "/test/source/sample.txt",
            "file_size": 1000
        }
    
    @pytest.mark.asyncio
    async def test_handle_space_check_with_job_size(
        self, processor_with_space_checking, sample_job, mock_space_checker
    ):
        """Test space check using file size from job."""
        # Setup mock
        expected_result = SpaceCheckResult(
            has_space=True, 
            reason="OK",
            available_bytes=10000000000,
            required_bytes=1000,
            file_size_bytes=1000,
            safety_margin_bytes=0
        )
        mock_space_checker.check_space_for_file.return_value = expected_result
        
        # Handle space check
        result = await processor_with_space_checking.handle_space_check(sample_job)
        
        # Verify result
        assert result == expected_result
        mock_space_checker.check_space_for_file.assert_called_once_with(1000)
    
    @pytest.mark.asyncio
    async def test_handle_space_check_fallback_to_tracked_file(
        self, processor_with_space_checking, mock_space_checker, mock_state_manager
    ):
        """Test space check falling back to tracked file for size."""
        # Job without file_size
        job = {"file_path": "/test/source/sample.txt"}
        
        # Setup mocks
        tracked_file = TrackedFile(
            file_path="/test/source/sample.txt",
            file_size=2000,
            status=FileStatus.READY
        )
        mock_state_manager.get_file.return_value = tracked_file
        expected_result = SpaceCheckResult(
            has_space=True, 
            reason="OK",
            available_bytes=10000000000,
            required_bytes=2000,
            file_size_bytes=2000,
            safety_margin_bytes=0
        )
        mock_space_checker.check_space_for_file.return_value = expected_result
        
        # Handle space check
        result = await processor_with_space_checking.handle_space_check(job)
        
        # Verify result
        assert result == expected_result
        mock_space_checker.check_space_for_file.assert_called_once_with(2000)
    
    @pytest.mark.asyncio
    async def test_handle_space_check_no_space_checker(self, processor, sample_job):
        """Test space check when no space checker is configured."""
        # Handle space check
        result = await processor.handle_space_check(sample_job)
        
        # Verify result (should assume space is available)
        assert result.has_space is True
        assert "No space checker configured" in result.reason


class TestJobPreparation:
    """Test job preparation functionality."""
    
    @pytest.fixture
    def sample_job(self):
        """Create a sample job for testing."""
        return {
            "file_path": "/test/source/subdir/sample.txt",
            "file_size": 1000
        }
    
    @pytest.fixture
    def sample_tracked_file(self):
        """Create a sample tracked file."""
        return TrackedFile(
            file_path="/test/source/subdir/sample.txt",
            file_size=1000,
            status=FileStatus.READY
        )
    
    @pytest.mark.asyncio
    async def test_prepare_file_for_copy_success(
        self, processor, sample_job, sample_tracked_file, 
        mock_state_manager, mock_copy_strategy_factory
    ):
        """Test successful file preparation."""
        # Setup mocks
        mock_state_manager.get_file.return_value = sample_tracked_file
        
        # Prepare file
        with patch('app.utils.file_operations.calculate_relative_path') as mock_rel_path, \
             patch('app.utils.file_operations.generate_conflict_free_path') as mock_conflict_free:
            
            mock_rel_path.return_value = Path("subdir/sample.txt")
            mock_conflict_free.return_value = Path("/test/dest/subdir/sample.txt")
            
            prepared = await processor.prepare_file_for_copy(sample_job)
        
        # Verify result
        assert prepared is not None
        assert prepared.tracked_file == sample_tracked_file
        assert prepared.strategy_name == "NormalFileCopyStrategy"
        assert prepared.initial_status == FileStatus.COPYING
        assert prepared.destination_path == Path("/test/dest/subdir/sample.txt")
    
    @pytest.mark.asyncio
    async def test_prepare_file_for_copy_growing_strategy(
        self, processor, sample_job, sample_tracked_file, 
        mock_state_manager, mock_copy_strategy_factory
    ):
        """Test file preparation with growing file strategy."""
        # Setup mocks for growing file strategy
        mock_strategy = Mock()
        mock_strategy.__class__.__name__ = "GrowingFileCopyStrategy"
        mock_copy_strategy_factory.get_strategy.return_value = mock_strategy
        mock_state_manager.get_file.return_value = sample_tracked_file
        
        # Prepare file
        with patch('app.utils.file_operations.calculate_relative_path') as mock_rel_path, \
             patch('app.utils.file_operations.generate_conflict_free_path') as mock_conflict_free:
            
            mock_rel_path.return_value = Path("subdir/sample.txt")
            mock_conflict_free.return_value = Path("/test/dest/subdir/sample.txt")
            
            prepared = await processor.prepare_file_for_copy(sample_job)
        
        # Verify result
        assert prepared is not None
        assert prepared.strategy_name == "GrowingFileCopyStrategy"
        assert prepared.initial_status == FileStatus.GROWING_COPY
    
    @pytest.mark.asyncio
    async def test_prepare_file_for_copy_file_not_found(
        self, processor, sample_job, mock_state_manager
    ):
        """Test file preparation when file not found."""
        # Setup mock to return None
        mock_state_manager.get_file.return_value = None
        
        # Prepare file
        prepared = await processor.prepare_file_for_copy(sample_job)
        
        # Verify result
        assert prepared is None


class TestJobFinalization:
    """Test job finalization functionality."""
    
    @pytest.fixture
    def sample_job(self):
        """Create a sample job for testing."""
        return {
            "file_path": "/test/source/sample.txt",
            "file_size": 1000
        }
    
    @pytest.mark.asyncio
    async def test_finalize_job_success(
        self, processor, sample_job, mock_job_queue, mock_state_manager
    ):
        """Test successful job finalization."""
        # Setup mocks
        mock_job_queue.mark_job_completed.return_value = None
        mock_state_manager.update_file_status.return_value = None
        
        # Finalize job
        await processor.finalize_job_success(sample_job, 1000)
        
        # Verify calls
        mock_job_queue.mark_job_completed.assert_called_once_with(sample_job)
        mock_state_manager.update_file_status.assert_called_once_with(
            sample_job["file_path"],
            FileStatus.COMPLETED,
            copy_progress=100.0,
            error_message=None,
            retry_count=0
        )
    
    @pytest.mark.asyncio
    async def test_finalize_job_failure(
        self, processor, sample_job, mock_job_queue, mock_state_manager
    ):
        """Test job failure finalization."""
        # Setup mocks
        mock_job_queue.mark_job_failed.return_value = None
        mock_state_manager.update_file_status.return_value = None
        
        # Test error
        test_error = Exception("Test copy error")
        
        # Finalize job
        await processor.finalize_job_failure(sample_job, test_error)
        
        # Verify calls
        mock_job_queue.mark_job_failed.assert_called_once_with(sample_job, "Test copy error")
        mock_state_manager.update_file_status.assert_called_once_with(
            sample_job["file_path"],
            FileStatus.FAILED,
            error_message="Test copy error"
        )
    
    @pytest.mark.asyncio
    async def test_finalize_job_max_retries(
        self, processor, sample_job, mock_job_queue, mock_state_manager
    ):
        """Test job finalization after max retries."""
        # Setup mocks
        mock_job_queue.mark_job_failed.return_value = None
        mock_state_manager.update_file_status.return_value = None
        
        # Finalize job
        await processor.finalize_job_max_retries(sample_job)
        
        # Verify calls
        mock_job_queue.mark_job_failed.assert_called_once_with(sample_job, "Max retry attempts reached")
        mock_state_manager.update_file_status.assert_called_once_with(
            sample_job["file_path"],
            FileStatus.FAILED,
            error_message="Failed after 3 retry attempts"
        )
    
    @pytest.mark.asyncio
    async def test_finalize_job_success_with_error(
        self, processor, sample_job, mock_job_queue, mock_state_manager
    ):
        """Test job finalization when finalization itself fails."""
        # Setup mock to raise exception
        mock_job_queue.mark_job_completed.side_effect = Exception("Queue error")
        
        # Finalize job (should not raise exception)
        await processor.finalize_job_success(sample_job, 1000)
        
        # Verify the error was handled gracefully (logged but not raised)
        mock_job_queue.mark_job_completed.assert_called_once()


class TestEdgeCases:
    """Test edge cases and error conditions."""
    
    @pytest.mark.asyncio
    async def test_space_shortage_without_retry_manager(self, processor, mock_space_checker):
        """Test space shortage handling without retry manager."""
        # Create processor with space checker but no retry manager
        processor.space_checker = mock_space_checker
        
        job = {"file_path": "/test/file.txt", "file_size": 1000}
        space_check = SpaceCheckResult(
            has_space=False, 
            reason="No space",
            available_bytes=500,
            required_bytes=1000,
            file_size_bytes=1000,
            safety_margin_bytes=0
        )
        
        # Test space shortage handling
        result = await processor._handle_space_shortage_result(job, space_check)
        
        # Verify result
        assert result.success is False
        assert result.space_shortage is True
        assert result.retry_scheduled is False  # No retry manager
    
    @pytest.mark.asyncio
    async def test_space_shortage_retry_scheduling_fails(
        self, processor_with_space_checking, mock_space_retry_manager
    ):
        """Test space shortage when retry scheduling fails."""
        # Setup retry manager to fail
        mock_space_retry_manager.schedule_space_retry.side_effect = Exception("Retry error")
        
        job = {"file_path": "/test/file.txt", "file_size": 1000}
        space_check = SpaceCheckResult(
            has_space=False, 
            reason="No space",
            available_bytes=500,
            required_bytes=1000,
            file_size_bytes=1000,
            safety_margin_bytes=0
        )
        
        # Test space shortage handling
        result = await processor_with_space_checking._handle_space_shortage_result(job, space_check)
        
        # Verify result (should fallback to marking as failed)
        assert result.success is False
        assert result.space_shortage is True
        # retry_scheduled might be False due to fallback behavior