"""
Integration test for Phase 3.4 Service Integration.

Test to verify that the new modular architecture works correctly:
- FileCopyExecutor for file copying
- CopyStrategyFactory for configuration
- JobProcessor for job workflow
- Integration with existing strategies and error handling
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, AsyncMock

from app.config import Settings
from app.models import TrackedFile, FileStatus
from app.services.file_copier import FileCopyService
from app.services.state_manager import StateManager
from app.services.job_queue import JobQueueService


@pytest.fixture
def test_settings():
    """Create test settings."""
    settings = Mock(spec=Settings)
    settings.source_directory = "/source"
    settings.destination_directory = "/dest"
    settings.use_temporary_file = True
    settings.enable_growing_file_support = True
    settings.enable_pre_copy_space_check = False
    settings.max_retry_attempts = 3
    settings.retry_delay_seconds = 1
    settings.global_retry_delay_seconds = 5
    settings.copy_progress_update_interval = 2
    settings.growing_file_chunk_size_kb = 32
    settings.max_concurrent_copies = 1
    return settings


@pytest.fixture
def mock_state_manager():
    """Create mock state manager."""
    state_manager = Mock(spec=StateManager)
    state_manager.add_file = AsyncMock()
    state_manager.get_file = AsyncMock()
    state_manager.update_file_status = AsyncMock()
    state_manager.get_all_files = AsyncMock(return_value=[])
    return state_manager


@pytest.fixture
def mock_job_queue():
    """Create mock job queue."""
    job_queue = Mock(spec=JobQueueService)
    job_queue.get_next_job = AsyncMock()
    job_queue.mark_job_completed = AsyncMock()
    job_queue.mark_job_failed = AsyncMock()
    return job_queue


@pytest.fixture
def file_copier_service(test_settings, mock_state_manager, mock_job_queue):
    """Create FileCopyService with new integrated architecture."""
    return FileCopyService(
        settings=test_settings,
        state_manager=mock_state_manager,
        job_queue=mock_job_queue
    )


class TestServiceIntegration:
    """Test integration of new modular services."""
    
    def test_service_initialization(self, file_copier_service):
        """Test that all new services are properly initialized."""
        service = file_copier_service
        
        # Verify new services are initialized
        assert hasattr(service, 'new_copy_strategy_factory')
        assert hasattr(service, 'file_copy_executor')
        assert hasattr(service, 'job_processor')
        
        # Verify legacy services still exist for compatibility
        assert hasattr(service, 'copy_strategy_factory')
        assert hasattr(service, 'destination_checker')
        assert hasattr(service, 'error_handler')
        assert hasattr(service, 'statistics_tracker')
        
        # Test that services can provide info
        factory_info = service.new_copy_strategy_factory.get_factory_info()
        assert 'default_chunk_size' in factory_info
        assert 'available_strategies' in factory_info
        
        executor_info = service.file_copy_executor.get_executor_info()
        assert 'chunk_size' in executor_info
        assert 'default_strategy' in executor_info
        
        processor_info = service.job_processor.get_processor_info()
        assert 'space_checking_enabled' in processor_info
        assert 'copy_strategies_available' in processor_info
    
    @pytest.mark.asyncio
    async def test_copy_strategy_factory_integration(self, file_copier_service):
        """Test CopyStrategyFactory configuration generation."""
        factory = file_copier_service.new_copy_strategy_factory
        
        # Test normal file configuration
        normal_file = TrackedFile(
            file_path="/source/normal.mxf",
            file_size=50 * 1024 * 1024,  # 50MB
            status=FileStatus.READY,
            is_growing_file=False,
            discovered_at=datetime.now()
        )
        
        config = factory.get_executor_config(normal_file)
        assert config.strategy_name == "normal_temp"
        assert config.use_temp_file is True
        assert config.chunk_size == 64 * 1024
        assert config.is_growing_file is False
        
        # Test growing file configuration
        growing_file = TrackedFile(
            file_path="/source/growing.mxv",
            file_size=200 * 1024 * 1024,  # 200MB
            status=FileStatus.READY,
            is_growing_file=True,
            discovered_at=datetime.now()
        )
        
        config = factory.get_executor_config(growing_file)
        assert config.strategy_name == "growing_stream"
        assert config.use_temp_file is False
        assert config.chunk_size == 32 * 1024
        assert config.is_growing_file is True
        
        # Test progress callback creation
        callback = factory.get_progress_callback(normal_file)
        assert callable(callback)
    
    @pytest.mark.asyncio
    async def test_file_copy_executor_integration(self, file_copier_service, tmp_path):
        """Test FileCopyExecutor with real files."""
        executor = file_copier_service.file_copy_executor
        
        # Create test files
        source_file = tmp_path / "source" / "test.txt"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("Test content for integration test")
        
        dest_file = tmp_path / "dest" / "test.txt"
        dest_file.parent.mkdir(parents=True)
        
        # Test copy operation
        result = await executor.copy_file(source_file, dest_file)
        
        assert result.success is True
        assert result.bytes_copied > 0
        assert result.elapsed_seconds > 0
        assert dest_file.exists()
        assert dest_file.read_text() == "Test content for integration test"
        
        # Test copy verification
        verification_result = await executor.verify_copy(source_file, dest_file)
        assert verification_result is True
    
    @pytest.mark.asyncio
    async def test_job_processor_integration(self, file_copier_service, mock_state_manager):
        """Test JobProcessor workflow with mock file."""
        processor = file_copier_service.job_processor
        
        # Setup mock tracked file
        tracked_file = TrackedFile(
            file_path="/source/test.mxf",
            file_size=1024 * 1024,  # 1MB
            status=FileStatus.READY,
            is_growing_file=False,
            discovered_at=datetime.now()
        )
        
        mock_state_manager.get_file.return_value = tracked_file
        
        # Create test job
        job = {
            "file_path": "/source/test.mxf",
            "file_size": 1024 * 1024,
            "added_to_queue_at": datetime.now(),
            "retry_count": 0
        }
        
        # Test job processing (will fail due to missing source file, but tests workflow)
        result = await processor.process_job(job)
        
        # Verify result structure
        assert hasattr(result, 'success')
        assert hasattr(result, 'file_path')
        assert hasattr(result, 'error_message')
        assert hasattr(result, 'retry_scheduled')
        assert hasattr(result, 'space_shortage')
        
        # Verify file_path is correct
        assert result.file_path == "/source/test.mxf"
    
    @pytest.mark.asyncio
    async def test_statistics_integration(self, file_copier_service):
        """Test enhanced statistics with new service information."""
        stats = await file_copier_service.get_copy_statistics()
        
        # Verify basic statistics structure
        assert "is_running" in stats
        assert "total_files_copied" in stats
        assert "performance" in stats
        assert "error_handling" in stats
        
        # Verify new architecture information is included
        assert "architecture" in stats
        assert "copy_strategy_factory" in stats["architecture"]
        assert "file_copy_executor" in stats["architecture"]
        assert "job_processor" in stats["architecture"]
        
        # Verify architecture details
        factory_stats = stats["architecture"]["copy_strategy_factory"]
        assert "default_chunk_size" in factory_stats
        assert "available_strategies" in factory_stats
        
        executor_stats = stats["architecture"]["file_copy_executor"]
        assert "chunk_size" in executor_stats
        assert "default_strategy" in executor_stats
        
        processor_stats = stats["architecture"]["job_processor"]
        assert "space_checking_enabled" in processor_stats
        assert "copy_strategies_available" in processor_stats
    
    def test_strategy_compatibility(self, file_copier_service):
        """Test that both old and new strategy factories work."""
        # Test old factory (for backward compatibility)
        old_factory = file_copier_service.copy_strategy_factory
        old_strategies = old_factory.get_available_strategies()
        assert isinstance(old_strategies, dict)
        assert len(old_strategies) > 0
        
        # Test new factory
        new_factory = file_copier_service.new_copy_strategy_factory
        new_strategies = new_factory.get_available_strategies()
        assert isinstance(new_strategies, dict)
        assert len(new_strategies) > 0
        
        # Verify different strategy approaches
        assert "normal" in old_strategies
        assert "normal_temp" in new_strategies
    
    def test_service_info_methods(self, file_copier_service):
        """Test that all services provide comprehensive info methods."""
        # Test copy strategy factory info
        factory_info = file_copier_service.new_copy_strategy_factory.get_factory_info()
        required_factory_keys = [
            'default_chunk_size', 'large_file_chunk_size', 'growing_file_chunk_size',
            'large_file_threshold', 'growing_file_support', 'available_strategies'
        ]
        for key in required_factory_keys:
            assert key in factory_info
        
        # Test file copy executor info
        executor_info = file_copier_service.file_copy_executor.get_executor_info()
        required_executor_keys = [
            'chunk_size', 'progress_update_interval', 'use_temporary_file', 'default_strategy'
        ]
        for key in required_executor_keys:
            assert key in executor_info
        
        # Test job processor info
        processor_info = file_copier_service.job_processor.get_processor_info()
        required_processor_keys = [
            'space_checking_enabled', 'max_retry_attempts', 
            'space_retry_manager_available', 'copy_strategies_available'
        ]
        for key in required_processor_keys:
            assert key in processor_info


class TestNewArchitectureBehavior:
    """Test specific behavior of the new architecture."""
    
    @pytest.mark.asyncio
    async def test_process_job_delegates_to_job_processor(self, file_copier_service, mock_state_manager):
        """Test that _process_job correctly delegates to JobProcessor."""
        # Setup tracked file
        tracked_file = TrackedFile(
            file_path="/source/test.mxf",
            file_size=1024 * 1024,
            status=FileStatus.READY,
            is_growing_file=False,
            discovered_at=datetime.now()
        )
        mock_state_manager.get_file.return_value = tracked_file
        
        # Mock the job processor to return success
        file_copier_service.job_processor.process_job = AsyncMock()
        from app.services.consumer.job_processor import ProcessResult
        
        success_result = ProcessResult(
            success=True,
            file_path="/source/test.mxf",
            error_message=None,
            retry_scheduled=False,
            space_shortage=False
        )
        file_copier_service.job_processor.process_job.return_value = success_result
        
        # Test job
        job = {
            "file_path": "/source/test.mxf",
            "file_size": 1024 * 1024,
            "added_to_queue_at": datetime.now(),
            "retry_count": 0
        }
        
        # Process job
        await file_copier_service._process_job(job)
        
        # Verify JobProcessor was called
        file_copier_service.job_processor.process_job.assert_called_once_with(job)
    
    def test_copy_single_file_uses_new_executor(self, file_copier_service):
        """Test that _copy_single_file uses the new FileCopyExecutor and CopyStrategyFactory."""
        # Verify that the new services are used in the method
        # This is more of a structural test since we can't easily mock the deep integration
        
        # Check that the services are properly initialized and accessible
        assert file_copier_service.new_copy_strategy_factory is not None
        assert file_copier_service.file_copy_executor is not None
        
        # Verify that they have the expected interfaces
        assert hasattr(file_copier_service.new_copy_strategy_factory, 'get_executor_config')
        assert hasattr(file_copier_service.new_copy_strategy_factory, 'get_progress_callback')
        assert hasattr(file_copier_service.file_copy_executor, 'copy_file')
        assert hasattr(file_copier_service.file_copy_executor, 'verify_copy')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])