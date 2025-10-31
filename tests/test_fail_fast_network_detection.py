"""
Test fail-fast network error detection in Phase 3 implementation.

Tests that copy strategies immediately fail when network errors are detected
instead of waiting for the full operation to complete.
"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.config import Settings
from app.models import FileStatus, TrackedFile
from app.services.copy.network_error_detector import NetworkError, NetworkErrorDetector
from app.services.copy.growing_copy import GrowingFileCopyStrategy
from app.services.copy.file_copy_executor import FileCopyExecutor
from app.services.state_manager import StateManager


class TestFailFastNetworkErrorDetection:
    """Test immediate network error detection in copy strategies."""

    @pytest.mark.asyncio
    async def test_network_error_detector_fails_fast_on_write_error(self):
        """Test that network error detector immediately fails on network write errors."""
        detector = NetworkErrorDetector("/fake/dest/path")

        # Simulate network-related IOError
        network_error = OSError(5, "Input/output error")

        with pytest.raises(NetworkError) as exc_info:
            detector.check_write_error(network_error, "test write")

        assert "Network error during test write" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_network_error_detector_detects_errno_22(self):
        """Test that network error detector catches errno 22 (Invalid argument) as network error."""
        detector = NetworkErrorDetector("/fake/dest/path")

        # Simulate errno 22 which can be network-related on Windows
        invalid_arg_error = OSError(22, "Invalid argument")

        with pytest.raises(NetworkError) as exc_info:
            detector.check_write_error(invalid_arg_error, "test write")

        assert "Network error during test write" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_network_error_detector_connectivity_check(self):
        """Test that connectivity checks detect when destination becomes unavailable."""
        # Create a temporary directory that we can control
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            test_dest = Path(temp_dir) / "test_file.mxv"
            detector = NetworkErrorDetector(str(test_dest), check_interval_bytes=100)

            # First check should pass
            await detector.check_destination_connectivity(150)  # Trigger check

            # Now simulate destination becoming unavailable by removing directory
            import shutil

            shutil.rmtree(temp_dir)

            # Next check should fail
            with pytest.raises(NetworkError) as exc_info:
                await detector.check_destination_connectivity(
                    300
                )  # Trigger another check

            assert "no longer accessible" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_growing_copy_strategy_fails_fast_on_network_error(self):
        """Test that GrowingFileCopyStrategy chunk copy immediately fails when network error is detected."""
        settings = Settings()
        settings.growing_file_min_size_mb = 1  # 1MB minimum
        settings.growing_file_chunk_size_kb = 64  # 64KB chunks
        settings.growing_file_poll_interval_seconds = 0.1
        settings.growing_file_safety_margin_mb = 0.1
        settings.growing_copy_pause_ms = 0
        settings.use_temporary_file = False

        state_manager = AsyncMock(spec=StateManager)
        file_copy_executor = AsyncMock(spec=FileCopyExecutor)

        strategy = GrowingFileCopyStrategy(
            settings=settings,
            state_manager=state_manager,
            file_copy_executor=file_copy_executor,
        )

        tracked_file = TrackedFile(
            file_path="c:\\test\\growing.mxv",
            file_size=2000000,  # 2MB file
        )

        # Test the chunk copy method directly instead of the full growing copy loop
        from app.services.copy.network_error_detector import NetworkErrorDetector

        network_detector = NetworkErrorDetector("/fake/dest", check_interval_bytes=100)

        # Mock destination file that fails on write
        mock_dst = AsyncMock()
        mock_dst.write.side_effect = OSError(5, "Input/output error")  # Network error

        # Mock source file operations
        with patch("aiofiles.open") as mock_aiofiles:
            mock_src = AsyncMock()
            mock_src.read.return_value = b"x" * 65536  # 64KB chunk
            mock_src.seek = AsyncMock()

            mock_aiofiles.return_value.__aenter__.return_value = mock_src

            # Test _copy_chunk_range method directly - should fail fast on network error
            with pytest.raises(NetworkError) as exc_info:
                await strategy._copy_chunk_range(
                    source_path="c:\\test\\growing.mxv",
                    dst=mock_dst,
                    start_bytes=0,
                    end_bytes=65536,  # 64KB
                    chunk_size=65536,
                    tracked_file=tracked_file,
                    current_file_size=2000000,
                    pause_ms=0,
                    network_detector=network_detector,
                )

            assert "Network error during growing copy chunk write" in str(
                exc_info.value
            )

    @pytest.mark.asyncio
    async def test_growing_copy_strategy_detects_errno_22_as_network_error(self):
        """Test that GrowingFileCopyStrategy properly detects errno 22 as network error."""
        settings = Settings()
        settings.growing_file_min_size_mb = 1
        settings.use_temporary_file = False

        state_manager = AsyncMock(spec=StateManager)
        file_copy_executor = AsyncMock(spec=FileCopyExecutor)

        strategy = GrowingFileCopyStrategy(
            settings=settings,
            state_manager=state_manager,
            file_copy_executor=file_copy_executor,
        )

        tracked_file = TrackedFile(
            file_path="c:\\test\\growing.mxv",
            file_size=2000000,
        )

        # Mock a general exception with errno 22 that should be caught as network error
        errno_22_error = OSError(22, "Invalid argument")

        # Mock the _copy_growing_file method to raise errno 22
        with patch.object(strategy, "_copy_growing_file", side_effect=errno_22_error):
            with patch(
                "app.services.copy_strategies.aiofiles.os.path.getsize",
                return_value=2000000,
            ):  # Mock file size check
                with patch("pathlib.Path.exists", return_value=False):
                    with patch("pathlib.Path.mkdir"):
                        # Should catch errno 22 and convert to NetworkError
                        with pytest.raises(NetworkError) as exc_info:
                            await strategy.copy_file(
                                "c:\\test\\growing.mxv",
                                "c:\\test\\dest.mxv",
                                tracked_file,
                            )

                        assert "Network error during growing copy" in str(
                            exc_info.value
                        )
                        assert "Invalid argument" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_error_classifier_handles_network_error_immediately(self):
        """Test that error classifier properly handles NetworkError for immediate failure."""
        from app.services.consumer.job_error_classifier import JobErrorClassifier
        from app.services.storage_monitor.storage_monitor import StorageMonitorService

        storage_monitor = AsyncMock(spec=StorageMonitorService)
        storage_monitor.get_destination_info.return_value = None

        classifier = JobErrorClassifier(storage_monitor)

        # Test NetworkError classification
        network_error = NetworkError("Network connectivity lost during copy")
        status, reason = classifier.classify_copy_error(
            network_error, "c:\\test\\file.mxf"
        )

        assert status == FileStatus.FAILED
        assert "Network failure detected" in reason
        assert "Network connectivity lost" in reason
