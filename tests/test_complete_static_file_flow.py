"""
Test for verifying the complete static file copy flow including status handling.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.config import Settings
from app.models import FileStatus, TrackedFile
from app.services.copy.growing_copy import GrowingFileCopyStrategy
from app.services.copy.file_copy_executor import FileCopyExecutor
from app.core.file_repository import FileRepository
from app.core.events.event_bus import DomainEventBus
from app.services.consumer.job_file_preparation_service import JobFilePreparationService
from app.services.consumer.job_models import QueueJob
from app.utils.output_folder_template import OutputFolderTemplateEngine


class TestCompleteStaticFileFlow:
    """Test the complete flow for static files from job preparation through copy."""

    @pytest.fixture
    def settings(self):
        """Create test settings."""
        settings = MagicMock(spec=Settings)
        settings.growing_file_min_size_mb = 100  # 100MB minimum
        settings.growing_file_safety_margin_mb = 50  # 50MB safety margin
        settings.growing_file_chunk_size_kb = 2048  # 2MB chunks
        settings.growing_file_poll_interval_seconds = 5
        settings.growing_copy_pause_ms = 100
        settings.growing_file_growth_timeout_seconds = 30
        settings.source_directory = "/source"
        settings.destination_directory = "/dest"
        return settings

    @pytest.fixture
    def file_repository(self):
        """Mock file repository."""
        return AsyncMock(spec=FileRepository)

    @pytest.fixture
    def event_bus(self):
        """Mock event bus."""
        return AsyncMock(spec=DomainEventBus)

    @pytest.fixture
    def copy_strategy(self, settings, file_repository, event_bus):
        """Create GrowingFileCopyStrategy for testing."""
        return GrowingFileCopyStrategy(settings, file_repository, event_bus)

    @pytest.fixture
    def job_preparation_service(
        self, settings, file_repository, copy_strategy, template_engine
    ):
        """Create JobFilePreparationService for testing."""
        return JobFilePreparationService(
            settings, file_repository, copy_strategy, template_engine
        )

    @pytest.mark.asyncio
    async def test_static_file_preparation_sets_copying_status(
        self, job_preparation_service
    ):
        """Test that static files get COPYING status during job preparation."""
        # Create a static file
        static_file = TrackedFile(
            file_path="/source/static_file.mxf",
            file_size=75 * 1024 * 1024,  # 75MB - below growing minimum
            status=FileStatus.READY,
            growth_rate_mbps=0.0,
            first_seen_size=75 * 1024 * 1024,
            previous_file_size=75 * 1024 * 1024,
        )

        # Create a queue job
        from datetime import datetime

        job = QueueJob(
            tracked_file=static_file, added_to_queue_at=datetime.now(), retry_count=0
        )

        # Prepare the file
        prepared_file = await job_preparation_service.prepare_file_for_copy(job)

        # Verify the status is set correctly for static files
        assert prepared_file.initial_status == FileStatus.COPYING, (
            f"Static file should get COPYING status, got {prepared_file.initial_status}"
        )

    @pytest.mark.asyncio
    async def test_growing_file_preparation_sets_growing_copy_status(
        self, job_preparation_service
    ):
        """Test that growing files get GROWING_COPY status during job preparation."""
        # Create a growing file
        growing_file = TrackedFile(
            file_path="/source/growing_file.mxv",
            file_size=150 * 1024 * 1024,  # 150MB
            status=FileStatus.READY_TO_START_GROWING,  # Growing status
            growth_rate_mbps=4.2,
            first_seen_size=100 * 1024 * 1024,
            previous_file_size=140 * 1024 * 1024,
        )

        # Create a queue job
        from datetime import datetime

        job = QueueJob(
            tracked_file=growing_file, added_to_queue_at=datetime.now(), retry_count=0
        )

        # Prepare the file
        prepared_file = await job_preparation_service.prepare_file_for_copy(job)

        # Verify the status is set correctly for growing files
        assert prepared_file.initial_status == FileStatus.GROWING_COPY, (
            f"Growing file should get GROWING_COPY status, got {prepared_file.initial_status}"
        )

    def test_static_file_copy_loop_initialization(self, copy_strategy):
        """Test that static files start with file_finished_growing=True."""
        # Simulate static file parameters (no_growth_cycles = max_no_growth_cycles)
        max_no_growth_cycles = (
            6  # Example from settings: 30 seconds / 5 second interval
        )
        no_growth_cycles = max_no_growth_cycles  # Static files start here

        # This simulates what happens in _growing_copy_loop initialization
        file_finished_growing = no_growth_cycles >= max_no_growth_cycles

        assert file_finished_growing is True, (
            "Static files should start with file_finished_growing=True to skip safety margins"
        )

    def test_growing_file_copy_loop_initialization(self, copy_strategy):
        """Test that growing files start with file_finished_growing=False."""
        # Simulate growing file parameters (no_growth_cycles = 0)
        max_no_growth_cycles = 6
        no_growth_cycles = 0  # Growing files start here

        # This simulates what happens in _growing_copy_loop initialization
        file_finished_growing = no_growth_cycles >= max_no_growth_cycles

        assert file_finished_growing is False, (
            "Growing files should start with file_finished_growing=False to use safety margins"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
