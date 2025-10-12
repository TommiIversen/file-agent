"""
Tests for JobSpaceManager service.

Validates space checking and space shortage handling functionality
extracted from JobProcessor for SRP compliance.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

from app.config import Settings
from app.models import FileStatus, SpaceCheckResult, TrackedFile
from app.services.consumer.job_space_manager import JobSpaceManager
from app.services.consumer.job_models import ProcessResult


@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    settings = MagicMock()
    settings.enable_pre_copy_space_check = True
    return settings


@pytest.fixture
def mock_state_manager():
    """Mock state manager for testing."""
    return AsyncMock()


@pytest.fixture
def mock_job_queue():
    """Mock job queue for testing."""
    return AsyncMock()


@pytest.fixture
def mock_space_checker():
    """Mock space checker for testing."""
    return MagicMock()


@pytest.fixture
def mock_space_retry_manager():
    """Mock space retry manager for testing."""
    return AsyncMock()


@pytest.fixture
def job_space_manager(
    mock_settings,
    mock_state_manager,
    mock_job_queue,
    mock_space_checker,
    mock_space_retry_manager
):
    """Create JobSpaceManager instance for testing."""
    return JobSpaceManager(
        settings=mock_settings,
        state_manager=mock_state_manager,
        job_queue=mock_job_queue,
        space_checker=mock_space_checker,
        space_retry_manager=mock_space_retry_manager
    )


class TestJobSpaceManager:
    """Test cases for JobSpaceManager."""

    def test_should_check_space_enabled(self, job_space_manager):
        """Test space checking when enabled with space checker available."""
        result = job_space_manager.should_check_space()
        assert result is True

    def test_should_check_space_disabled(self, job_space_manager):
        """Test space checking when disabled."""
        job_space_manager.settings.enable_pre_copy_space_check = False
        result = job_space_manager.should_check_space()
        assert result is False

    def test_should_check_space_no_checker(self, job_space_manager):
        """Test space checking when no space checker available."""
        job_space_manager.space_checker = None
        result = job_space_manager.should_check_space()
        assert result is False

    @pytest.mark.asyncio
    async def test_check_space_for_job_with_checker(self, job_space_manager):
        """Test space checking with available space checker."""
        # Arrange
        job = {"file_path": "/test/file.txt", "file_size": 1000}
        expected_result = SpaceCheckResult(
            has_space=True,
            available_bytes=5000,
            required_bytes=1000,
            file_size_bytes=1000,
            safety_margin_bytes=100,
            reason="Sufficient space"
        )
        job_space_manager.space_checker.check_space_for_file.return_value = expected_result

        # Act
        result = await job_space_manager.check_space_for_job(job)

        # Assert
        assert result == expected_result
        job_space_manager.space_checker.check_space_for_file.assert_called_once_with(1000)

    @pytest.mark.asyncio
    async def test_check_space_for_job_no_checker(self, job_space_manager):
        """Test space checking without space checker."""
        # Arrange
        job_space_manager.space_checker = None
        job = {"file_path": "/test/file.txt", "file_size": 1000}

        # Act
        result = await job_space_manager.check_space_for_job(job)

        # Assert
        assert result.has_space is True
        assert result.required_bytes == 1000
        assert result.reason == "No space checker configured"

    @pytest.mark.asyncio
    async def test_check_space_for_job_fallback_to_tracked_file(self, job_space_manager):
        """Test space checking with fallback to tracked file for size."""
        # Arrange
        job = {"file_path": "/test/file.txt"}  # No file_size in job
        tracked_file = TrackedFile(
            file_path="/test/file.txt",
            file_size=2000,
            status=FileStatus.DISCOVERED
        )
        job_space_manager.state_manager.get_file.return_value = tracked_file
        
        expected_result = SpaceCheckResult(
            has_space=True,
            available_bytes=5000,
            required_bytes=2000,
            file_size_bytes=2000,
            safety_margin_bytes=100,
            reason="Sufficient space"
        )
        job_space_manager.space_checker.check_space_for_file.return_value = expected_result

        # Act
        result = await job_space_manager.check_space_for_job(job)

        # Assert
        job_space_manager.space_checker.check_space_for_file.assert_called_once_with(2000)

    @pytest.mark.asyncio
    async def test_handle_space_shortage_with_retry_manager(self, job_space_manager):
        """Test space shortage handling with retry manager available."""
        # Arrange
        job = {"file_path": "/test/file.txt"}
        space_check = SpaceCheckResult(
            has_space=False,
            available_bytes=500,
            required_bytes=1000,
            file_size_bytes=1000,
            safety_margin_bytes=100,
            reason="Insufficient space"
        )

        # Act
        result = await job_space_manager.handle_space_shortage(job, space_check)

        # Assert
        assert isinstance(result, ProcessResult)
        assert result.success is False
        assert result.space_shortage is True
        assert result.retry_scheduled is True
        assert "Insufficient space" in result.error_message

    @pytest.mark.asyncio
    async def test_handle_space_shortage_no_retry_manager(self, job_space_manager):
        """Test space shortage handling without retry manager."""
        # Arrange
        job_space_manager.space_retry_manager = None
        job = {"file_path": "/test/file.txt"}
        space_check = SpaceCheckResult(
            has_space=False,
            available_bytes=500,
            required_bytes=1000,
            file_size_bytes=1000,
            safety_margin_bytes=100,
            reason="Insufficient space"
        )

        # Act
        result = await job_space_manager.handle_space_shortage(job, space_check)

        # Assert
        assert isinstance(result, ProcessResult)
        assert result.success is False
        assert result.space_shortage is True
        assert result.retry_scheduled is False
        job_space_manager.state_manager.update_file_status.assert_called_once()
        job_space_manager.job_queue.mark_job_failed.assert_called_once()

    def test_get_space_manager_info(self, job_space_manager):
        """Test getting space manager configuration info."""
        # Act
        info = job_space_manager.get_space_manager_info()

        # Assert
        assert "space_checking_enabled" in info
        assert "space_checker_available" in info
        assert "space_retry_manager_available" in info
        assert "pre_copy_space_check_setting" in info
        assert info["space_checking_enabled"] is True
        assert info["space_checker_available"] is True
        assert info["space_retry_manager_available"] is True