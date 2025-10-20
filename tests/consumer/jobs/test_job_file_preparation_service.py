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


@pytest.fixture
def preparer():
    """Simple file preparer for testing."""
    settings = MagicMock(source_directory="/src", destination_directory="/dst")
    state_manager = AsyncMock()
    copy_strategy_factory = MagicMock()
    template_engine = MagicMock()
    template_engine.is_enabled.return_value = True

    return JobFilePreparationService(
        settings, state_manager, copy_strategy_factory, template_engine
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
            tracked_file=tracked_file,
            added_to_queue_at=datetime.now()
        )
        strategy = MagicMock(__class__=MagicMock(__name__="StandardCopyStrategy"))

        preparer.state_manager.get_file_by_path.return_value = tracked_file
        preparer.copy_strategy_factory.get_strategy.return_value = strategy

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
        assert result.tracked_file == tracked_file
        assert result.strategy_name == "StandardCopyStrategy"
        assert result.initial_status == FileStatus.COPYING
        assert result.destination_path == Path("/dst/test.mxf")

    @pytest.mark.asyncio
    async def test_prepare_file_not_found(self, preparer):
        """Test file preparation when file not found."""
        # Simulate a job with a tracked_file that is None
        job = QueueJob(
            tracked_file=None,
            added_to_queue_at=datetime.now()
        )
        preparer.state_manager.get_file_by_path.return_value = None

        result = await preparer.prepare_file_for_copy(job)

        assert result is None

    def test_determine_initial_status_growing(self, preparer):
        """Test status determination for growing strategy."""
        status = preparer._determine_initial_status("GrowingFileCopyStrategy")
        assert status == FileStatus.GROWING_COPY

    def test_determine_initial_status_standard(self, preparer):
        """Test status determination for standard strategy."""
        status = preparer._determine_initial_status("StandardCopyStrategy")
        assert status == FileStatus.COPYING
