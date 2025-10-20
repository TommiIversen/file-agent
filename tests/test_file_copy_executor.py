"""
Tests for File Copy Executor Service.

Comprehensive test suite covering:
- Direct and temporary file copy strategies
- Progress tracking and callbacks
- File verification
- Error handling and cleanup
- Performance metrics
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch

from app.config import Settings
from app.services.copy.file_copy_executor import (
    FileCopyExecutor,
    CopyResult,
    CopyProgress,
)


class TestFileCopyExecutorBasics:
    """Test basic FileCopyExecutor functionality."""

    @pytest.fixture
    def settings(self):
        """Create test settings."""
        return Settings(
            source_directory="/test/source",
            destination_directory="/test/dest",
            use_temporary_file=True,
            copy_progress_update_interval=10,
            chunk_size_kb=2048,  # Simple 2MB chunks
        )

    @pytest.fixture
    def executor(self, settings):
        """Create FileCopyExecutor instance."""
        return FileCopyExecutor(settings)

    def test_initialization(self, executor, settings):
        """Test FileCopyExecutor initialization."""
        assert executor.settings == settings
        assert executor.chunk_size == settings.chunk_size_kb * 1024
        assert (
            executor.progress_update_interval == settings.copy_progress_update_interval
        )

    def test_initialization_with_default_progress_interval(self):
        """Test initialization with default progress interval."""
        settings = Settings(
            source_directory="/test/source",
            destination_directory="/test/dest",
            use_temporary_file=True,
            chunk_size_kb=2048,
        )
        executor = FileCopyExecutor(settings)
        assert executor.progress_update_interval == 1  # Default value

    def test_get_executor_info(self, executor):
        """Test executor configuration info."""
        info = executor.get_executor_info()

        expected_info = {
            "chunk_size_kb": 2048,  # Simple 2MB chunks
            "progress_update_interval": 10,  # From settings (fixed)
            "use_temporary_file": True,
            "default_strategy": "temp_file",
        }

        assert info == expected_info

    def test_get_executor_info_direct_mode(self):
        """Test executor info for direct copy mode."""
        settings = Settings(
            source_directory="/test/source",
            destination_directory="/test/dest",
            use_temporary_file=False,
            chunk_size_kb=2048,
        )
        executor = FileCopyExecutor(settings)
        info = executor.get_executor_info()

        assert info["use_temporary_file"] is False
        assert info["default_strategy"] == "direct"


class TestCopyResultAndProgress:
    """Test CopyResult and CopyProgress dataclasses."""

    def test_copy_result_creation(self):
        """Test CopyResult creation and properties."""
        start_time = datetime.now()
        end_time = datetime.now()

        result = CopyResult(
            success=True,
            source_path=Path("/source/file.txt"),
            destination_path=Path("/dest/file.txt"),
            bytes_copied=1024 * 1024,  # 1MB
            elapsed_seconds=2.0,
            start_time=start_time,
            end_time=end_time,
        )

        assert result.success is True
        assert result.bytes_copied == 1024 * 1024
        assert result.transfer_rate_bytes_per_sec == 512 * 1024  # 0.5MB/s
        assert result.transfer_rate_mb_per_sec == 0.5
        assert result.size_mb == 1.0

    def test_copy_result_error_case(self):
        """Test CopyResult for error cases."""
        result = CopyResult(
            success=False,
            source_path=Path("/source/file.txt"),
            destination_path=Path("/dest/file.txt"),
            bytes_copied=0,
            elapsed_seconds=0.1,
            start_time=datetime.now(),
            end_time=datetime.now(),
            error_message="Test error",
        )

        assert result.success is False
        assert result.transfer_rate_bytes_per_sec == 0.0
        assert result.error_message == "Test error"

    def test_copy_result_summary_success(self):
        """Test CopyResult success summary."""
        result = CopyResult(
            success=True,
            source_path=Path("/source/test.txt"),
            destination_path=Path("/dest/test.txt"),
            bytes_copied=2 * 1024 * 1024,  # 2MB
            elapsed_seconds=1.0,
            start_time=datetime.now(),
            end_time=datetime.now(),
        )

        summary = result.get_summary()
        assert "Copy successful" in summary
        assert "test.txt" in summary
        assert "2.00 MB" in summary
        assert "2.00 MB/s" in summary

    def test_copy_result_summary_failure(self):
        """Test CopyResult failure summary."""
        result = CopyResult(
            success=False,
            source_path=Path("/source/test.txt"),
            destination_path=Path("/dest/test.txt"),
            bytes_copied=0,
            elapsed_seconds=0.1,
            start_time=datetime.now(),
            end_time=datetime.now(),
            error_message="File not found",
        )

        summary = result.get_summary()
        assert "Copy failed" in summary
        assert "test.txt" in summary
        assert "File not found" in summary

    def test_copy_progress_creation(self):
        """Test CopyProgress creation and properties."""
        progress = CopyProgress(
            bytes_copied=512 * 1024,  # 0.5MB
            total_bytes=1024 * 1024,  # 1MB
            elapsed_seconds=1.0,
            current_rate_bytes_per_sec=512 * 1024,
        )

        assert progress.progress_percent == 50.0
        assert progress.progress_percent_int == 50
        assert progress.remaining_bytes == 512 * 1024
        assert progress.estimated_remaining_seconds == 1.0

    def test_copy_progress_edge_cases(self):
        """Test CopyProgress edge cases."""
        # Zero total bytes
        progress = CopyProgress(
            bytes_copied=100,
            total_bytes=0,
            elapsed_seconds=1.0,
            current_rate_bytes_per_sec=100,
        )
        assert progress.progress_percent == 0.0

        # Over 100% progress (should cap at 100)
        progress = CopyProgress(
            bytes_copied=1500,
            total_bytes=1000,
            elapsed_seconds=1.0,
            current_rate_bytes_per_sec=1500,
        )
        assert progress.progress_percent == 100.0

        # Zero rate
        progress = CopyProgress(
            bytes_copied=500,
            total_bytes=1000,
            elapsed_seconds=1.0,
            current_rate_bytes_per_sec=0,
        )
        assert progress.estimated_remaining_seconds == 0.0


class TestFileCopyWithRealFiles:
    """Test FileCopyExecutor with real file operations."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)

    @pytest.fixture
    def settings(self, temp_dir):
        """Create test settings with temp directory."""
        return Settings(
            source_directory=str(temp_dir / "source"),
            destination_directory=str(temp_dir / "dest"),
            use_temporary_file=True,
            copy_progress_update_interval=10,
        )

    @pytest.fixture
    def executor(self, settings):
        """Create FileCopyExecutor instance."""
        return FileCopyExecutor(settings)

    @pytest.fixture
    def test_file(self, temp_dir):
        """Create a test file with content."""
        source_dir = temp_dir / "source"
        source_dir.mkdir(parents=True, exist_ok=True)

        test_file = source_dir / "test.txt"
        test_content = "Hello, World!" * 1000  # Create some content
        test_file.write_text(test_content)

        return test_file

    @pytest.mark.asyncio
    async def test_copy_with_temp_file_success(self, executor, test_file, temp_dir):
        """Test successful copy with temporary file strategy."""
        dest_dir = temp_dir / "dest"
        dest_file = dest_dir / "test.txt"

        # Mock progress callback
        progress_callback = Mock()

        result = await executor.copy_with_temp_file(
            test_file, dest_file, progress_callback
        )

        # Verify result
        assert result.success is True
        assert result.source_path == test_file
        assert result.destination_path == dest_file
        assert result.bytes_copied == test_file.stat().st_size
        assert result.elapsed_seconds > 0
        assert result.verification_successful is True
        assert result.temp_file_used is True
        assert result.temp_file_path is not None

        # Verify file was copied correctly
        assert dest_file.exists()
        assert dest_file.read_text() == test_file.read_text()

        # Verify temp file was cleaned up
        assert not result.temp_file_path.exists()

        # Verify progress callback was called
        assert progress_callback.called

    @pytest.mark.asyncio
    async def test_copy_direct_success(self, executor, test_file, temp_dir):
        """Test successful direct copy."""
        dest_dir = temp_dir / "dest"
        dest_file = dest_dir / "test.txt"

        result = await executor.copy_direct(test_file, dest_file)

        # Verify result
        assert result.success is True
        assert result.source_path == test_file
        assert result.destination_path == dest_file
        assert result.bytes_copied == test_file.stat().st_size
        assert result.temp_file_used is False

        # Verify file was copied correctly
        assert dest_file.exists()
        assert dest_file.read_text() == test_file.read_text()

    @pytest.mark.asyncio
    async def test_copy_file_uses_configured_strategy(self, test_file, temp_dir):
        """Test that copy_file uses the configured strategy."""
        # Test with temp file strategy
        settings_temp = Settings(
            source_directory=str(temp_dir / "source"),
            destination_directory=str(temp_dir / "dest"),
            use_temporary_file=True,
        )
        executor_temp = FileCopyExecutor(settings_temp)

        dest_file = temp_dir / "dest" / "test_temp.txt"
        result = await executor_temp.copy_file(test_file, dest_file)

        assert result.success is True
        assert result.temp_file_used is True

        # Test with direct strategy
        settings_direct = Settings(
            source_directory=str(temp_dir / "source"),
            destination_directory=str(temp_dir / "dest"),
            use_temporary_file=False,
        )
        executor_direct = FileCopyExecutor(settings_direct)

        dest_file_direct = temp_dir / "dest" / "test_direct.txt"
        result_direct = await executor_direct.copy_file(test_file, dest_file_direct)

        assert result_direct.success is True
        assert result_direct.temp_file_used is False

    @pytest.mark.asyncio
    async def test_verify_copy_success(self, executor, test_file, temp_dir):
        """Test successful file verification."""
        dest_file = temp_dir / "dest" / "test.txt"
        dest_file.parent.mkdir(parents=True, exist_ok=True)

        # Copy file manually
        shutil.copy2(test_file, dest_file)

        # Verify
        is_valid = await executor.verify_copy(test_file, dest_file)
        assert is_valid is True

    @pytest.mark.asyncio
    async def test_verify_copy_failure_missing_dest(
        self, executor, test_file, temp_dir
    ):
        """Test verification failure when destination doesn't exist."""
        dest_file = temp_dir / "dest" / "nonexistent.txt"

        is_valid = await executor.verify_copy(test_file, dest_file)
        assert is_valid is False

    @pytest.mark.asyncio
    async def test_verify_copy_failure_size_mismatch(
        self, executor, test_file, temp_dir
    ):
        """Test verification failure when file sizes don't match."""
        dest_file = temp_dir / "dest" / "test.txt"
        dest_file.parent.mkdir(parents=True, exist_ok=True)

        # Create destination with different size
        dest_file.write_text("Different content")

        is_valid = await executor.verify_copy(test_file, dest_file)
        assert is_valid is False


class TestErrorHandlingAndCleanup:
    """Test error handling and cleanup behavior."""

    @pytest.fixture
    def settings(self):
        """Create test settings."""
        return Settings(
            source_directory="/test/source",
            destination_directory="/test/dest",
            use_temporary_file=True,
        )

    @pytest.fixture
    def executor(self, settings):
        """Create FileCopyExecutor instance."""
        return FileCopyExecutor(settings)

    @pytest.mark.asyncio
    async def test_copy_with_temp_file_source_not_found(self, executor):
        """Test copy with temp file with non-existent source."""
        source = Path("/nonexistent/source.txt")
        dest = Path("/test/dest/output.txt")

        result = await executor.copy_with_temp_file(source, dest)

        assert result.success is False
        # Don't check for specific error message text since it can be in different languages
        # Just check that we have an error message and the copy failed
        assert result.error_message is not None
        assert len(result.error_message) > 0
        assert result.bytes_copied == 0

    @pytest.mark.asyncio
    async def test_copy_direct_source_not_found(self, executor):
        """Test direct copy with non-existent source."""
        source = Path("/nonexistent/source.txt")
        dest = Path("/test/dest/output.txt")

        result = await executor.copy_direct(source, dest)

        assert result.success is False
        assert result.bytes_copied == 0
        assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_copy_with_temp_file_verification_failure(self, executor):
        """Test temp file copy with verification failure."""
        source = Path("/test/source.txt")
        dest = Path("/test/dest.txt")
        temp_path = Path("/test/dest.txt.tmp")

        # Mock temp file path creation
        with patch(
            "app.utils.file_operations.create_temp_file_path", return_value=temp_path
        ):
            # Mock pathlib operations
            with patch("pathlib.Path.mkdir"):
                with patch("pathlib.Path.exists", return_value=True):
                    with patch("pathlib.Path.unlink"):
                        # Mock the copy operation to succeed but verification to fail
                        copy_result = Mock()
                        copy_result.success = True
                        copy_result.bytes_copied = 100

                        with patch.object(
                            executor, "_perform_copy", return_value=copy_result
                        ):
                            with patch.object(
                                executor, "verify_copy", return_value=False
                            ):
                                result = await executor.copy_with_temp_file(
                                    source, dest
                                )

        assert result.success is False
        assert result.verification_successful is False
        assert "verification failed" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_copy_direct_verification_failure(self, executor):
        """Test direct copy with verification failure."""
        source = Path("/test/source.txt")
        dest = Path("/test/dest.txt")

        # Mock pathlib operations
        with patch("pathlib.Path.mkdir"):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.unlink"):
                    # Mock the copy operation to succeed but verification to fail
                    copy_result = Mock()
                    copy_result.success = True
                    copy_result.bytes_copied = 100

                    with patch.object(
                        executor, "_perform_copy", return_value=copy_result
                    ):
                        with patch.object(executor, "verify_copy", return_value=False):
                            result = await executor.copy_direct(source, dest)

        assert result.success is False
        assert result.verification_successful is False


class TestProgressTracking:
    """Test progress tracking functionality."""

    @pytest.fixture
    def settings(self):
        """Create test settings with frequent progress updates."""
        return Settings(
            source_directory="/test/source",
            destination_directory="/test/dest",
            use_temporary_file=False,
            copy_progress_update_interval=1,  # Very frequent updates for testing
        )

    @pytest.fixture
    def executor(self, settings):
        """Create FileCopyExecutor instance."""
        return FileCopyExecutor(settings)

    @pytest.mark.asyncio
    @patch("aiofiles.open")
    async def test_progress_callback_called(self, mock_open, executor):
        """Test that progress callback is called during copy."""
        source = Path("/test/source.txt")
        dest = Path("/test/dest.txt")
        progress_callback = Mock()

        # Mock file operations without mocking Path.stat directly
        with patch("os.stat") as mock_stat:
            mock_stat.return_value.st_size = 1000

            # Mock async file operations
            mock_src = AsyncMock()
            mock_dst = AsyncMock()

            # Simulate multiple chunks being read
            mock_src.read.side_effect = [
                b"x" * 100,  # First chunk
                b"x" * 100,  # Second chunk
                b"x" * 100,  # Third chunk
                b"",  # EOF
            ]

            mock_context = AsyncMock()
            mock_context.__aenter__.side_effect = [mock_src, mock_dst]
            mock_context.__aexit__ = AsyncMock(return_value=False)
            mock_open.return_value = mock_context

            with patch("pathlib.Path.mkdir"):
                # Mock verification to succeed
                with patch.object(executor, "verify_copy", return_value=True):
                    await executor.copy_direct(source, dest, progress_callback)

        # Verify progress callback was called
        assert progress_callback.called

        # Verify progress callback received CopyProgress objects
        calls = progress_callback.call_args_list
        for call_args in calls:
            args, kwargs = call_args
            progress = args[0]
            assert isinstance(progress, CopyProgress)
            assert progress.bytes_copied > 0
            assert progress.total_bytes == 1000
            assert progress.elapsed_seconds >= 0

    @pytest.mark.asyncio
    @patch("aiofiles.open")
    async def test_progress_callback_exception_handling(self, mock_open, executor):
        """Test that progress callback exceptions don't break copy operation."""
        source = Path("/test/source.txt")
        dest = Path("/test/dest.txt")

        # Create a callback that raises an exception
        def failing_callback(progress):
            raise ValueError("Test callback error")

        # Mock file operations without mocking Path.stat directly
        with patch("os.stat") as mock_stat:
            mock_stat.return_value.st_size = 100

            mock_src = AsyncMock()
            mock_dst = AsyncMock()
            mock_src.read.side_effect = [b"x" * 100, b""]

            mock_context = AsyncMock()
            mock_context.__aenter__.side_effect = [mock_src, mock_dst]
            mock_context.__aexit__ = AsyncMock(return_value=False)
            mock_open.return_value = mock_context

            with patch("pathlib.Path.mkdir"):
                with patch.object(executor, "verify_copy", return_value=True):
                    # Copy should still succeed despite callback failure
                    result = await executor.copy_direct(source, dest, failing_callback)

        assert result.success is True  # Copy should succeed despite callback error


class TestPerformanceMetrics:
    """Test performance metrics calculation."""

    def test_transfer_rate_calculation(self):
        """Test transfer rate calculations in CopyResult."""
        result = CopyResult(
            success=True,
            source_path=Path("/source.txt"),
            destination_path=Path("/dest.txt"),
            bytes_copied=10 * 1024 * 1024,  # 10MB
            elapsed_seconds=5.0,  # 5 seconds
            start_time=datetime.now(),
            end_time=datetime.now(),
        )

        # 10MB in 5 seconds = 2MB/s
        assert result.transfer_rate_mb_per_sec == 2.0
        assert result.transfer_rate_bytes_per_sec == 2 * 1024 * 1024

    def test_zero_time_transfer_rate(self):
        """Test transfer rate with zero elapsed time."""
        result = CopyResult(
            success=True,
            source_path=Path("/source.txt"),
            destination_path=Path("/dest.txt"),
            bytes_copied=1000,
            elapsed_seconds=0.0,
            start_time=datetime.now(),
            end_time=datetime.now(),
        )

        assert result.transfer_rate_bytes_per_sec == 0.0
        assert result.transfer_rate_mb_per_sec == 0.0

    def test_progress_time_estimation(self):
        """Test time estimation in CopyProgress."""
        progress = CopyProgress(
            bytes_copied=1 * 1024 * 1024,  # 1MB copied
            total_bytes=4 * 1024 * 1024,  # 4MB total
            elapsed_seconds=1.0,
            current_rate_bytes_per_sec=1 * 1024 * 1024,  # 1MB/s
        )

        # 3MB remaining at 1MB/s = 3 seconds
        assert progress.estimated_remaining_seconds == 3.0
        assert progress.remaining_bytes == 3 * 1024 * 1024
