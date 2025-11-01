"""
Simple tests for JobFilePreparationService - follows 2:1 line ratio rule.

Tests file preparation and destination path logic.
Max 70 lines for 139-line service.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
from datetime import datetime

from app.services.consumer.job_file_preparation_service import JobFilePreparationService
from app.models import FileStatus, TrackedFile
from app.services.consumer.job_models import QueueJob
from app.services.copy.growing_copy import GrowingFileCopyStrategy


@pytest.fixture
def preparer():
    """Simple file preparer for testing."""
    settings = MagicMock(source_directory="/src", destination_directory="/dst")
    file_repository = AsyncMock()
    event_bus = AsyncMock()
    copy_strategy = AsyncMock(spec=GrowingFileCopyStrategy)
    copy_strategy.__class__.__name__ = "GrowingFileCopyStrategy"
    template_engine = MagicMock()
    template_engine.is_enabled.return_value = True

    return JobFilePreparationService(
        settings, file_repository, event_bus, copy_strategy, template_engine
    )


class TestJobFilePreparationService:
    """Simple, focused tests for file preparation."""

    @pytest.mark.asyncio
    async def test_prepare_file_success(self, preparer):
        """Test successful file preparation."""
        tracked_file = TrackedFile(
            file_path="/src/test.mxf", file_size=1000, status=FileStatus.READY
        )
        job = QueueJob(
            file_id=tracked_file.id,
            file_path=tracked_file.file_path,
            file_size=tracked_file.file_size,
            creation_time=tracked_file.creation_time,
            is_growing_at_queue_time=False,
            added_to_queue_at=datetime.now(),
        )

        preparer.file_repository.get_by_id.return_value = tracked_file

        preparer.copy_strategy._is_file_currently_growing.return_value = False

        # Mock the utils functions
        with (
            patch(
                "app.services.consumer.job_file_preparation_service.build_destination_path_with_template"
            ) as mock_build,
            patch(
                "app.services.consumer.job_file_preparation_service.generate_conflict_free_path"
            ) as mock_generate,
        ):
            mock_build.return_value = "/dst/test.mxf"
            mock_generate.return_value = Path("/dst/test.mxf")

            result = await preparer.prepare_file_for_copy(job)

        assert result is not None
        assert result.job.file_id == tracked_file.id
        assert result.strategy_name == "GrowingFileCopyStrategy"
        assert result.initial_status == FileStatus.COPYING
        assert result.destination_path == Path("/dst/test.mxf")

    @pytest.mark.asyncio
    async def test_prepare_file_not_found(self, preparer):
        """Test file preparation when file not found."""

        mock_tracked_file = MagicMock(spec=TrackedFile)
        mock_tracked_file.id = "nonexistent-id"
        mock_tracked_file.file_path = "/src/nonexistent.mxf"
        job = QueueJob(
            file_id=mock_tracked_file.id,
            file_path=mock_tracked_file.file_path,
            file_size=0,
            creation_time=None,
            is_growing_at_queue_time=False,
            added_to_queue_at=datetime.now(),
        )
        preparer.file_repository.get_by_id.return_value = None

        result = await preparer.prepare_file_for_copy(job)

        assert result is not None
        assert result.job is not None
        assert result.strategy_name == "GrowingFileCopyStrategy"

    @pytest.mark.asyncio
    async def test_determine_initial_status(self, preparer):
        """Test status determination for growing and static files."""
        # Create a mock tracked_file
        mock_tracked_file = MagicMock(spec=TrackedFile)
        mock_tracked_file.id = "test-id"
        mock_tracked_file.file_path = "/mock/file.mxf"
        mock_tracked_file.status = FileStatus.READY

        job = QueueJob(
            file_id=mock_tracked_file.id,
            file_path=mock_tracked_file.file_path,
            file_size=0,
            creation_time=None,
            is_growing_at_queue_time=True,  # Set to True for growing file case
            added_to_queue_at=datetime.now(),
        )

        preparer.file_repository.get_by_id.return_value = mock_tracked_file

        # Test the growing file case
        status = await preparer._determine_file_status(job)
        assert status == FileStatus.GROWING_COPY

        # Test the static file case
        job.is_growing_at_queue_time = False  # Set to False for static file case
        status = await preparer._determine_file_status(job)
        assert status == FileStatus.COPYING
