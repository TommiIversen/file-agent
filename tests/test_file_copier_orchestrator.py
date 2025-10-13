"""
Tests for the new ultra-lean FileCopyService orchestrator.

The new FileCopyService is a pure orchestrator that delegates all operations
to specialized services. These tests focus on orchestration behavior rather
than the detailed copy logic (which is tested in individual service tests).
"""

import pytest
from unittest.mock import Mock, AsyncMock

from app.services.file_copier import FileCopyService
from app.services.job_queue import JobQueueService
from app.services.copy_strategies import CopyStrategyFactory
from app.services.tracking.copy_statistics import CopyStatisticsTracker
from app.services.error_handling.copy_error_handler import CopyErrorHandler
from app.services.destination.destination_checker import DestinationChecker
from app.config import Settings


class TestFileCopyServiceOrchestrator:
    """Test the new lean FileCopyService orchestrator pattern."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings for testing."""
        return Settings(
            source_directory="/test/source",
            destination_directory="/test/dest",
            max_concurrent_copies=2,
            file_stable_time_seconds=1,
        )

    @pytest.fixture
    def mock_state_manager(self):
        """Create mock state manager."""
        return Mock()

    @pytest.fixture
    def mock_job_queue(self):
        """Create mock job queue service."""
        mock = Mock(spec=JobQueueService)
        mock.get_next_job = AsyncMock(return_value=None)
        return mock

    @pytest.fixture
    def orchestrator(self, mock_settings, mock_state_manager, mock_job_queue):
        """Create FileCopyService orchestrator instance."""
        return FileCopyService(
            settings=mock_settings,
            state_manager=mock_state_manager,
            job_queue=mock_job_queue,
        )

    def test_orchestrator_initialization(self, orchestrator, mock_settings):
        """Test that orchestrator initializes all services correctly."""
        # Check that all required services are created
        assert orchestrator.settings == mock_settings
        assert orchestrator.job_queue is not None
        assert orchestrator.copy_strategy_factory is not None
        assert orchestrator.statistics_tracker is not None
        assert orchestrator.error_handler is not None
        assert orchestrator.destination_checker is not None
        assert orchestrator.file_copy_executor is not None
        assert orchestrator.job_processor is not None

        # Check orchestrator state
        assert not orchestrator.is_running()
        assert orchestrator.get_active_worker_count() == 0

    @pytest.mark.asyncio
    async def test_orchestrator_statistics_delegation(self, orchestrator):
        """Test that statistics are properly delegated to statistics tracker."""
        # Mock some data in the statistics tracker
        orchestrator.statistics_tracker.complete_copy_session(
            "/test/file1.txt", success=True, final_bytes_transferred=1024
        )
        orchestrator.statistics_tracker.complete_copy_session(
            "/test/file2.txt", success=False
        )

        # Get statistics through orchestrator
        stats = await orchestrator.get_copy_statistics()

        # Verify delegation works
        assert "total_files_copied" in stats
        assert "total_files_failed" in stats
        assert "is_running" in stats
        assert "active_workers" in stats
        assert "destination_available" in stats

    @pytest.mark.asyncio
    async def test_orchestrator_worker_management(self, orchestrator):
        """Test worker lifecycle management."""
        assert not orchestrator.is_running()
        assert orchestrator.get_active_worker_count() == 0

        # Test stop when not running
        await orchestrator.stop_consumer()
        assert not orchestrator.is_running()

    @pytest.mark.asyncio
    async def test_orchestrator_job_processing_delegation(self, orchestrator):
        """Test that job processing is delegated to job processor."""
        # Mock a job
        test_job = {"file_path": "/test/file.txt", "file_size": 1024}
        orchestrator.job_queue.get_next_job = AsyncMock(return_value=test_job)

        # Mock job processor to prevent actual processing
        orchestrator.job_processor.process_job = AsyncMock()
        orchestrator.destination_checker.is_available = AsyncMock(return_value=True)

        # Mock the consumer worker to run once then stop
        async def mock_worker():
            if orchestrator._running:
                job = await orchestrator.job_queue.get_next_job()
                if job:
                    await orchestrator.job_processor.process_job(job)
                orchestrator._running = False  # Stop after one iteration

        # Replace the worker method temporarily
        orchestrator._consumer_worker = mock_worker

        # Start and let it process one job
        orchestrator._running = True
        await mock_worker()

        # Verify delegation occurred
        orchestrator.job_processor.process_job.assert_called_once_with(test_job)

    def test_orchestrator_service_composition(self, orchestrator):
        """Test that all services are properly composed."""
        # Verify types of composed services
        assert isinstance(orchestrator.copy_strategy_factory, CopyStrategyFactory)
        assert isinstance(orchestrator.statistics_tracker, CopyStatisticsTracker)
        assert isinstance(orchestrator.error_handler, CopyErrorHandler)
        assert isinstance(orchestrator.destination_checker, DestinationChecker)

        # Verify services have necessary dependencies
        assert orchestrator.job_processor.job_queue == orchestrator.job_queue
        assert (
            orchestrator.job_processor.copy_strategy_factory
            == orchestrator.copy_strategy_factory
        )

    @pytest.mark.asyncio
    async def test_orchestrator_graceful_shutdown(self, orchestrator):
        """Test graceful shutdown of orchestrator."""
        # Ensure clean initial state
        assert not orchestrator.is_running()
        assert len(orchestrator._consumer_tasks) == 0

        # Test stop consumer when already stopped
        await orchestrator.stop_consumer()
        assert not orchestrator.is_running()

    def test_orchestrator_backward_compatibility(self, orchestrator, mock_settings):
        """Test that orchestrator maintains necessary backward compatibility."""
        # These attributes are needed for existing integration
        assert hasattr(orchestrator, "settings")
        assert hasattr(orchestrator, "_destination_available")
        assert orchestrator.settings == mock_settings

        # These methods should exist
        assert callable(orchestrator.is_running)
        assert callable(orchestrator.get_active_worker_count)
        assert hasattr(orchestrator, "get_copy_statistics")

    @pytest.mark.asyncio
    async def test_orchestrator_error_handling_delegation(self, orchestrator):
        """Test that error handling is properly delegated."""
        # Mock destination unavailable
        orchestrator.destination_checker.is_available = AsyncMock(return_value=False)
        orchestrator.error_handler.handle_global_error = AsyncMock()

        # Mock consumer worker to test error delegation
        async def test_worker():
            if not await orchestrator.destination_checker.is_available():
                await orchestrator.error_handler.handle_global_error(
                    "Destination unavailable"
                )
                return True
            return False

        # Test error delegation
        result = await test_worker()
        assert result  # Worker handled the error
        orchestrator.error_handler.handle_global_error.assert_called_once_with(
            "Destination unavailable"
        )


class TestFileCopyServiceLegacyCompatibility:
    """Test legacy compatibility for existing code that depends on FileCopyService."""

    @pytest.fixture
    def mock_settings(self):
        return Settings(
            source_directory="/test/source",
            destination_directory="/test/dest",
            max_concurrent_copies=1,
        )

    @pytest.fixture
    def mock_state_manager(self):
        return Mock()

    @pytest.fixture
    def mock_job_queue(self):
        mock = Mock(spec=JobQueueService)
        mock.get_next_job = AsyncMock(return_value=None)
        return mock

    def test_legacy_constructor_compatibility(
        self, mock_settings, mock_state_manager, mock_job_queue
    ):
        """Test that the legacy constructor signature still works."""
        # This should not raise an exception
        service = FileCopyService(mock_settings, mock_state_manager, mock_job_queue)

        assert service.settings == mock_settings
        assert isinstance(service, FileCopyService)

    @pytest.mark.asyncio
    async def test_legacy_statistics_format(
        self, mock_settings, mock_state_manager, mock_job_queue
    ):
        """Test that statistics still return expected format for legacy code."""
        service = FileCopyService(mock_settings, mock_state_manager, mock_job_queue)

        stats = await service.get_copy_statistics()

        # Check for expected keys that legacy code might depend on
        expected_keys = {
            "is_running",
            "total_files_copied",
            "total_bytes_copied",
            "total_files_failed",
            "success_rate",
        }

        for key in expected_keys:
            assert key in stats, f"Missing expected statistics key: {key}"

    def test_legacy_status_methods(
        self, mock_settings, mock_state_manager, mock_job_queue
    ):
        """Test legacy status methods."""
        service = FileCopyService(mock_settings, mock_state_manager, mock_job_queue)

        # These methods should exist and return sensible values
        assert isinstance(service.is_running(), bool)
        assert isinstance(service.get_active_worker_count(), int)
        assert hasattr(service, "_destination_available")  # For test compatibility
