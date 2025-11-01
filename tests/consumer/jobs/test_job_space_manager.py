"""
Tests for JobSpaceManager service.

Validates space checking and space shortage handling functionality
extracted from JobProcessor for SRP compliance.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from app.services.consumer.job_space_manager import JobSpaceManager
from app.models import SpaceCheckResult, TrackedFile, FileStatus
from app.services.consumer.job_models import ProcessResult, QueueJob
from app.core.file_repository import FileRepository
from app.core.events.event_bus import DomainEventBus
from app.services.job_queue import JobQueueService


@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    settings = MagicMock()
    settings.enable_pre_copy_space_check = True
    return settings


@pytest.fixture
def mock_file_repository():
    """Mock file repository for testing."""
    return AsyncMock(spec=FileRepository)


@pytest.fixture
def mock_event_bus():
    """Mock event bus for testing."""
    return AsyncMock(spec=DomainEventBus)


@pytest.fixture
def mock_job_queue():
    """Mock job queue for testing."""
    return AsyncMock(spec=JobQueueService)


@pytest.fixture
def mock_space_checker():
    """Mock space checker for testing."""
    return MagicMock()


@pytest.fixture
def mock_space_retry_manager():
    """Mock space retry manager for testing."""
    return AsyncMock()


@pytest.fixture
def space_manager(
    mock_settings,
    mock_file_repository,
    mock_event_bus,
    mock_job_queue,
    mock_space_checker,
    mock_space_retry_manager,
):
    """Create JobSpaceManager instance for testing."""
    return JobSpaceManager(
        settings=mock_settings,
        file_repository=mock_file_repository,
        event_bus=mock_event_bus,
        job_queue=mock_job_queue,
        space_checker=mock_space_checker,
        space_retry_manager=mock_space_retry_manager,
    )


class TestJobSpaceManager:
    """Test cases for JobSpaceManager."""

    def test_should_check_space_enabled(self, space_manager):
        """Test space checking when enabled with space checker available."""
        result = space_manager.should_check_space()
        assert result is True

    def test_should_check_space_disabled(self, space_manager):
        """Test space checking when disabled."""
        space_manager.settings.enable_pre_copy_space_check = False
        result = space_manager.should_check_space()
        assert result is False

    def test_should_check_space_no_checker(self, space_manager):
        """Test space checking when no space checker available."""
        space_manager.space_checker = None
        result = space_manager.should_check_space()
        assert result is False

    @pytest.mark.asyncio
    async def test_check_space_sufficient(self, space_manager):
        """Test space check with sufficient space."""
        tracked_file = TrackedFile(
            file_path="/test/file.txt", file_size=1000, status=FileStatus.READY
        )
        job = QueueJob(
            file_id=tracked_file.id,
            file_path=tracked_file.file_path,
            file_size=tracked_file.file_size,
            creation_time=tracked_file.creation_time,
            is_growing_at_queue_time=False,
            added_to_queue_at=datetime.now(),
        )
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

    @pytest.mark.asyncio
    async def test_handle_space_shortage_with_retry(self, space_manager):
        """Test space shortage handling with retry manager."""
        tracked_file = TrackedFile(
            file_path="/test/file.txt", file_size=1000, status=FileStatus.READY
        )
        job = QueueJob(
            file_id=tracked_file.id,
            file_path=tracked_file.file_path,
            file_size=tracked_file.file_size,
            creation_time=tracked_file.creation_time,
            is_growing_at_queue_time=False,
            added_to_queue_at=datetime.now(),
        )
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
        job = QueueJob(
            file_id=tracked_file.id,
            file_path=tracked_file.file_path,
            file_size=tracked_file.file_size,
            creation_time=tracked_file.creation_time,
            is_growing_at_queue_time=False,
            added_to_queue_at=datetime.now(),
        )
        space_manager.file_repository.get_by_id.return_value = tracked_file
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
        space_manager.file_repository.update.assert_called_once_with(tracked_file)
        space_manager.job_queue.mark_job_failed.assert_called_once()