"""
Simple tests for JobSpaceManager - follows 2:1 line ratio rule.

Tests space checking and shortage handling workflows.
Max 80 lines for 167-line service.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from app.services.consumer.job_space_manager import JobSpaceManager
from app.models import SpaceCheckResult, TrackedFile, FileStatus
from app.services.consumer.job_models import ProcessResult, QueueJob


@pytest.fixture
def space_manager():
    """Simple space manager for testing."""
    settings = MagicMock(enable_pre_copy_space_check=True)
    state_manager = AsyncMock()
    job_queue = AsyncMock()
    space_checker = MagicMock()
    space_retry_manager = AsyncMock()

    return JobSpaceManager(
        settings, state_manager, job_queue, space_checker, space_retry_manager
    )


class TestJobSpaceManager:
    """Simple, focused tests for space management."""

    def test_should_check_space_enabled(self, space_manager):
        """Test space checking when enabled."""
        assert space_manager.should_check_space() is True

    def test_should_check_space_disabled(self, space_manager):
        """Test space checking when disabled."""
        space_manager.settings.enable_pre_copy_space_check = False
        assert space_manager.should_check_space() is False

    @pytest.mark.asyncio
    async def test_check_space_sufficient(self, space_manager):
        """Test space check with sufficient space."""
        tracked_file = TrackedFile(
            file_path="/test/file.txt", file_size=1000, status=FileStatus.READY
        )
        job = QueueJob(tracked_file=tracked_file, added_to_queue_at=datetime.now())
        expected = SpaceCheckResult(
            has_space=True,
            available_bytes=5000,
            required_bytes=1000,
            file_size_bytes=1000,
            safety_margin_bytes=100,
            reason="OK",
        )
        space_manager.space_checker.check_space_for_file.return_value = expected

        result = await space_manager.check_space_for_job(job)

        assert result.has_space is True
        space_manager.space_checker.check_space_for_file.assert_called_once_with(1000)

    @pytest.mark.asyncio
    async def test_handle_space_shortage_with_retry(self, space_manager):
        """Test space shortage handling with retry manager."""
        tracked_file = TrackedFile(
            file_path="/test/file.txt", file_size=1000, status=FileStatus.READY
        )
        job = QueueJob(tracked_file=tracked_file, added_to_queue_at=datetime.now())
        space_check = SpaceCheckResult(
            has_space=False,
            available_bytes=500,
            required_bytes=1000,
            file_size_bytes=1000,
            safety_margin_bytes=100,
            reason="Insufficient",
        )

        result = await space_manager.handle_space_shortage(job, space_check)

        assert isinstance(result, ProcessResult)
        assert result.success is False
        assert result.space_shortage is True
        space_manager.space_retry_manager.schedule_space_retry.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_space_shortage_no_retry_manager(self, space_manager):
        """Test space shortage handling without retry manager."""
        space_manager.space_retry_manager = None
        tracked_file = TrackedFile(
            file_path="/test/file.txt", file_size=1000, status=FileStatus.READY
        )
        job = QueueJob(tracked_file=tracked_file, added_to_queue_at=datetime.now())
        space_check = SpaceCheckResult(
            has_space=False,
            available_bytes=500,
            required_bytes=1000,
            file_size_bytes=1000,
            safety_margin_bytes=100,
            reason="Insufficient",
        )

        result = await space_manager.handle_space_shortage(job, space_check)

        assert result.success is False
        assert result.space_shortage is True
        space_manager.state_manager.update_file_status_by_id.assert_called_once()
        space_manager.job_queue.mark_job_failed.assert_called_once()
