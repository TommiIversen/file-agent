"""
Tests for domain objects used in the scanner module.
Testing the domain objects ensures our primitive obsession fixes work correctly.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, AsyncMock
from app.services.scanner.domain_objects import FilePath, FileMetadata, ScanConfiguration


class TestFilePath:
    """Test the FilePath domain object."""

    def test_name_property(self):
        path = FilePath("/path/to/test_file.mxf")
        assert path.name == "test_file.mxf"

    def test_extension_property(self):
        path = FilePath("/path/to/test_file.MXF")
        assert path.extension == ".mxf"  # Should be lowercase

    def test_is_mxf_file(self):
        mxf_path = FilePath("/path/to/file.mxf")
        other_path = FilePath("/path/to/file.mp4")

        assert mxf_path.is_mxf_file()
        assert not other_path.is_mxf_file()

    def test_should_ignore(self):
        test_file = FilePath("/path/to/test_file.mxf")
        hidden_file = FilePath("/path/to/.hidden.mxf")
        normal_file = FilePath("/path/to/normal.mxf")

        assert test_file.should_ignore()
        assert hidden_file.should_ignore()
        assert not normal_file.should_ignore()

    @pytest.mark.asyncio
    async def test_exists(self):
        path = FilePath("/nonexistent/file.mxf")

        with patch('aiofiles.os.path.exists', new_callable=AsyncMock) as mock_exists:
            mock_exists.return_value = True
            assert await path.exists()

            mock_exists.return_value = False
            assert not await path.exists()


class TestFileMetadata:
    """Test the FileMetadata domain object."""

    def test_is_empty(self):
        empty_meta = FileMetadata(
            path=FilePath("/test.mxf"),
            size=0,
            last_write_time=datetime.now()
        )
        normal_meta = FileMetadata(
            path=FilePath("/test.mxf"),
            size=1024,
            last_write_time=datetime.now()
        )

        assert empty_meta.is_empty()
        assert not normal_meta.is_empty()

    def test_size_mb(self):
        meta = FileMetadata(
            path=FilePath("/test.mxf"),
            size=2 * 1024 * 1024,  # 2MB
            last_write_time=datetime.now()
        )

        assert meta.size_mb() == 2.0

    def test_is_stable(self):
        now = datetime.now()
        stable_time = now - timedelta(seconds=30)

        meta = FileMetadata(
            path=FilePath("/test.mxf"),
            size=1024,
            last_write_time=now
        )

        # File should be stable if last seen time is old enough
        assert meta.is_stable(timedelta(seconds=20), stable_time)

        # File should not be stable if last seen time is too recent
        recent_time = now - timedelta(seconds=10)
        assert not meta.is_stable(timedelta(seconds=20), recent_time)

    @pytest.mark.asyncio
    async def test_from_path_success(self):
        with patch('aiofiles.os.path.exists', new_callable=AsyncMock) as mock_exists, \
             patch('aiofiles.os.stat', new_callable=AsyncMock) as mock_stat:

            mock_exists.return_value = True
            mock_stat.return_value.st_size = 1024
            mock_stat.return_value.st_mtime = 1609459200  # 2021-01-01

            metadata = await FileMetadata.from_path("/test.mxf")

            assert metadata is not None
            assert metadata.size == 1024
            assert metadata.path.path == "/test.mxf"

    @pytest.mark.asyncio
    async def test_from_path_file_not_exists(self):
        with patch('aiofiles.os.path.exists', new_callable=AsyncMock) as mock_exists:
            mock_exists.return_value = False

            metadata = await FileMetadata.from_path("/nonexistent.mxf")
            assert metadata is None


class TestScanConfiguration:
    """Test the ScanConfiguration data class."""

    def test_creation(self):
        config = ScanConfiguration(
            source_directory="/source",
            polling_interval_seconds=5,
            file_stable_time_seconds=30,
            enable_growing_file_support=True,
            growing_file_min_size_mb=100,
            keep_completed_files_hours=24,
            max_completed_files_in_memory=1000
        )

        assert config.source_directory == "/source"
        assert config.polling_interval_seconds == 5
        assert config.file_stable_time_seconds == 30
        assert config.enable_growing_file_support is True
