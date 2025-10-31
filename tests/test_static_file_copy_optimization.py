"""
Test for static file copy optimization.

Tests that static files are copied at full speed without growing file delays.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import Settings
from app.models import FileStatus, TrackedFile
from app.services.copy.growing_copy import GrowingFileCopyStrategy
from app.services.copy.file_copy_executor import FileCopyExecutor
from app.core.file_repository import FileRepository
from app.core.events.event_bus import DomainEventBus


class TestStaticFileCopyOptimization:
    """Test that static files are copied optimally without growing file delays."""

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

    def test_static_file_detection_ready_status(self, copy_strategy):
        """Test that a file with READY status is detected as static."""
        # File that came from normal stability check (not growing)
        static_file = TrackedFile(
            file_path="/test/static_video.mxf",
            file_size=50 * 1024 * 1024,  # 50MB - below growing minimum
            status=FileStatus.READY,  # Key: READY status indicates static file
            growth_rate_mbps=0.0,
            first_seen_size=50 * 1024 * 1024,
            previous_file_size=50 * 1024 * 1024,
        )

        result = copy_strategy._is_file_currently_growing(static_file)
        assert result is False, "File with READY status should be detected as static"

    def test_static_file_detection_no_growth_history(self, copy_strategy):
        """Test that a file with no growth history is detected as static."""
        static_file = TrackedFile(
            file_path="/test/static_video.mxf",
            file_size=200 * 1024 * 1024,  # 200MB - above growing minimum
            status=FileStatus.READY,
            growth_rate_mbps=0.0,  # No growth rate
            first_seen_size=200 * 1024 * 1024,  # Same size since first seen
            previous_file_size=200 * 1024 * 1024,  # No size changes
        )

        result = copy_strategy._is_file_currently_growing(static_file)
        assert result is False, (
            "File with no growth history should be detected as static"
        )

    def test_growing_file_detection_status(self, copy_strategy):
        """Test that a file with growing status is detected as growing."""
        growing_file = TrackedFile(
            file_path="/test/growing_video.mxf",
            file_size=150 * 1024 * 1024,
            status=FileStatus.READY_TO_START_GROWING,  # Growing status
            growth_rate_mbps=5.2,
            first_seen_size=100 * 1024 * 1024,
            previous_file_size=140 * 1024 * 1024,
        )

        result = copy_strategy._is_file_currently_growing(growing_file)
        assert result is True, "File with growing status should be detected as growing"

    def test_growing_file_detection_growth_rate(self, copy_strategy):
        """Test that a file with growth rate is detected as growing."""
        growing_file = TrackedFile(
            file_path="/test/growing_video.mxv",
            file_size=180 * 1024 * 1024,
            status=FileStatus.READY,
            growth_rate_mbps=3.5,  # Has growth rate
            first_seen_size=100 * 1024 * 1024,
            previous_file_size=170 * 1024 * 1024,
        )

        result = copy_strategy._is_file_currently_growing(growing_file)
        assert result is True, "File with growth rate should be detected as growing"

    def test_growing_file_detection_size_increase(self, copy_strategy):
        """Test that a file that has grown is detected as growing."""
        growing_file = TrackedFile(
            file_path="/test/grown_video.mxf",
            file_size=200 * 1024 * 1024,  # Current size
            status=FileStatus.READY,
            growth_rate_mbps=0.0,  # No current rate
            first_seen_size=150 * 1024 * 1024,  # Originally smaller
            previous_file_size=190 * 1024 * 1024,  # Recently grew
        )

        result = copy_strategy._is_file_currently_growing(growing_file)
        assert result is True, "File that has grown should be detected as growing"

    @pytest.mark.asyncio
    async def test_static_file_copy_parameters(self, copy_strategy, file_repository):
        """Test that static files get optimized copy parameters."""
        # Create a static file
        static_file = TrackedFile(
            file_path="/test/static.mxf",
            file_size=75 * 1024 * 1024,  # 75MB
            status=FileStatus.READY,
            growth_rate_mbps=0.0,
            first_seen_size=75 * 1024 * 1024,
            previous_file_size=75 * 1024 * 1024,
        )

        # Mock the file repository to return our static file
        file_repository.get_by_path.return_value = static_file
        file_repository.get_by_id.return_value = static_file

        # Mock file operations
        with patch("aiofiles.os.path.getsize", return_value=75 * 1024 * 1024):
            with patch("aiofiles.os.makedirs"):
                with patch("aiofiles.open"):
                    with patch.object(
                        copy_strategy,
                        "_growing_copy_loop",
                        return_value=75 * 1024 * 1024,
                    ) as mock_loop:
                        with patch(
                            "app.services.copy_strategies._verify_file_integrity",
                            return_value=True,
                        ):
                            with patch("aiofiles.os.remove"):
                                # Call the copy method
                                result = await copy_strategy.copy_file(
                                    "/test/static.mxf", "/dest/static.mxf", static_file
                                )

        # Verify copy was successful
        assert result is True

        # Verify that _growing_copy_loop was called with static file optimizations
        mock_loop.assert_called_once()
        args = mock_loop.call_args[0]

        # Check arguments passed to _growing_copy_loop
        # args: source_path, dst, tracked_file, bytes_copied, last_file_size, no_growth_cycles, max_no_growth_cycles, safety_margin_bytes, chunk_size, poll_interval, pause_ms, network_detector

        safety_margin_bytes = args[7]  # 8th argument
        pause_ms = args[10]  # 11th argument
        no_growth_cycles = args[5]  # 6th argument
        max_no_growth_cycles = args[6]  # 7th argument

        # For static files, these should be optimized
        assert safety_margin_bytes == 0, (
            f"Static file should have 0 safety margin, got {safety_margin_bytes}"
        )
        assert pause_ms == 0, f"Static file should have 0 pause, got {pause_ms}"
        assert no_growth_cycles == max_no_growth_cycles, (
            "Static file should skip growth detection"
        )

    @pytest.mark.asyncio
    async def test_growing_file_copy_parameters(self, copy_strategy, file_repository):
        """Test that growing files get standard copy parameters with safety margins."""
        # Create a growing file
        growing_file = TrackedFile(
            file_path="/test/growing.mxv",
            file_size=150 * 1024 * 1024,  # 150MB
            status=FileStatus.READY_TO_START_GROWING,  # Growing status
            growth_rate_mbps=4.2,
            first_seen_size=100 * 1024 * 1024,
            previous_file_size=140 * 1024 * 1024,
        )

        # Mock the file repository
        file_repository.get_by_path.return_value = growing_file
        file_repository.get_by_id.return_value = growing_file

        # Mock file operations
        with patch("aiofiles.os.path.getsize", return_value=150 * 1024 * 1024):
            with patch("aiofiles.os.makedirs"):
                with patch("aiofiles.open"):
                    with patch.object(
                        copy_strategy,
                        "_growing_copy_loop",
                        return_value=150 * 1024 * 1024,
                    ) as mock_loop:
                        with patch(
                            "app.services.copy_strategies._verify_file_integrity",
                            return_value=True,
                        ):
                            with patch("aiofiles.os.remove"):
                                # Call the copy method
                                result = await copy_strategy.copy_file(
                                    "/test/growing.mxv",
                                    "/dest/growing.mxv",
                                    growing_file,
                                )

        # Verify copy was successful
        assert result is True

        # Verify that _growing_copy_loop was called with growing file parameters
        mock_loop.assert_called_once()
        args = mock_loop.call_args[0]

        safety_margin_bytes = args[7]  # 8th argument
        pause_ms = args[10]  # 11th argument
        no_growth_cycles = args[5]  # 6th argument

        # For growing files, these should use safety margins and delays
        assert safety_margin_bytes > 0, (
            f"Growing file should have safety margin, got {safety_margin_bytes}"
        )
        assert pause_ms > 0, f"Growing file should have pause, got {pause_ms}"
        assert no_growth_cycles == 0, "Growing file should start with 0 growth cycles"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
