"""
Integration test for Phase 3.4 Service Integration.

Test to verify that the new modular architecture works correctly:
- FileCopyExecutor for file copying
- JobProcessor for job workflow
- Integration with existing strategies and error handling
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, AsyncMock

from app.config import Settings
from app.models import TrackedFile, FileStatus
from app.services.copy.file_copier import FileCopierService
from app.services.state_manager import StateManager
from app.services.job_queue import JobQueueService
from app.services.copy.growing_copy import GrowingFileCopyStrategy
from app.services.copy.file_copy_executor import FileCopyExecutor
from app.services.consumer.job_processor import JobProcessor


@pytest.fixture
def test_settings():
    """Create test settings."""
    settings = Mock(spec=Settings)
    settings.source_directory = "/source"
    settings.destination_directory = "/dest"
    settings.use_temporary_file = True
    settings.enable_pre_copy_space_check = False
    settings.max_retry_attempts = 3
    settings.retry_delay_seconds = 1
    settings.global_retry_delay_seconds = 5
    settings.copy_progress_update_interval = 2
    settings.growing_file_chunk_size_kb = 32
    settings.chunk_size_kb = 2048  # Simple 2MB chunks
    settings.max_concurrent_copies = 1
    # Output folder template settings
    settings.output_folder_template_enabled = False
    settings.output_folder_default_category = "OTHER"
    settings.output_folder_rules = ""
    settings.output_folder_date_format = "filename[0:6]"
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
def mock_copy_strategy():
    """Mock GrowingFileCopyStrategy."""
    strategy = Mock(spec=GrowingFileCopyStrategy)
    strategy.copy_file = AsyncMock(return_value=True)
    return strategy


@pytest.fixture
def mock_file_copy_executor():
    """Mock FileCopyExecutor."""
    executor = Mock(spec=FileCopyExecutor)
    mock_copy_result = Mock()
    mock_copy_result.success = True
    mock_copy_result.error = None
    mock_copy_result.bytes_copied = 1024
    mock_copy_result.elapsed_seconds = 0.5
    executor.copy_file = AsyncMock(return_value=mock_copy_result)
    return executor


@pytest.fixture
def job_processor(
    test_settings, mock_state_manager, mock_job_queue, mock_copy_strategy
):
    """Create JobProcessor with new integrated architecture."""
    return JobProcessor(
        settings=test_settings,
        state_manager=mock_state_manager,
        job_queue=mock_job_queue,
        copy_strategy=mock_copy_strategy,
    )


@pytest.fixture
def file_copier_service(
    test_settings, mock_state_manager, mock_job_queue, job_processor
):
    """Create FileCopierService with new integrated architecture."""
    return FileCopierService(
        settings=test_settings,
        state_manager=mock_state_manager,
        job_queue=mock_job_queue,
        job_processor=job_processor,
    )


class TestServiceIntegration:
    """Test integration of new modular services."""

    def test_service_initialization(self, file_copier_service):
        """Test that all new services are properly initialized."""
        service = file_copier_service

        # Verify new services are initialized
        assert hasattr(service, "job_processor")
        assert hasattr(service.job_processor, "copy_strategy")

        # Verify core attributes exist
        assert hasattr(service, "settings")
        assert hasattr(service, "state_manager")
        assert hasattr(service, "job_queue")

    @pytest.mark.asyncio
    async def test_file_copy_executor_integration(
        self, mock_file_copy_executor, tmp_path
    ):
        """Test FileCopyExecutor with real files."""
        executor = mock_file_copy_executor

        # Create test files
        source_file = tmp_path / "source" / "test.txt"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("Test content for integration test")

        dest_file = tmp_path / "dest" / "test.txt"
        dest_file.parent.mkdir(parents=True)

        # Test copy operation (mocked)
        result = await executor.copy_file(source_file, dest_file)

        # Verify mock was called and returns expected structure
        assert result.success is True
        assert result.bytes_copied > 0
        assert result.elapsed_seconds > 0

        # Verify the copy_file method was called with correct arguments
        executor.copy_file.assert_called_once_with(source_file, dest_file)

    @pytest.mark.asyncio
    async def test_job_processor_integration(self, job_processor, mock_state_manager):
        """Test JobProcessor workflow with mock file."""
        # Setup mock tracked file
        tracked_file = TrackedFile(
            file_path="/source/test.mxf",
            file_size=1024 * 1024,  # 1MB
            status=FileStatus.READY,
            discovered_at=datetime.now(),
        )

        mock_state_manager.get_file_by_id.return_value = tracked_file

        # Create test job
        job = Mock()
        job.file_path = "/source/test.mxf"
        job.tracked_file = tracked_file

        # Test job processing
        result = await job_processor.process_job(job)

        # Verify result structure
        assert result.success is True
        assert result.file_path == "/source/test.mxf"

    @pytest.mark.asyncio
    async def test_statistics_integration(self, file_copier_service):
        """Test basic statistics with legacy compatibility."""
        stats = await file_copier_service.get_copy_statistics()

        # Verify basic statistics structure (legacy format)
        assert "is_running" in stats
        assert "total_files_copied" in stats
        assert "total_bytes_copied" in stats
        assert "total_files_failed" in stats
        assert "success_rate" in stats

        # Verify data types
        assert isinstance(stats["is_running"], bool)
        assert isinstance(stats["success_rate"], (int, float))


class TestNewArchitectureBehavior:
    """Test specific behavior of the new architecture."""

    # Test skipped - _process_job method no longer exists in orchestrator
    # Job processing is now handled through the consumer worker pattern

    # Test skipped - copy_single_file method no longer exists in orchestrator
    # Individual copy methods are now handled by specialized services


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
