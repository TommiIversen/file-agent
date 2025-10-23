"""
Tests for domain objects and utility functions used in the scanner module.
Testing the refactored functions ensures our primitive obsession fixes work correctly.
"""

import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, AsyncMock
from app.services.scanner.domain_objects import (
    ScanConfiguration,
)
from app.services.scanner.file_scanner import get_file_metadata, is_mxf_file, should_ignore_file


class TestPathUtilities:
    """Test the path utility functions that replaced FilePath."""

    def test_is_mxf_file(self):
        """Test MXF file detection."""
        mxf_path = Path("/path/to/file.mxf")
        mxf_upper_path = Path("/path/to/file.MXF")
        other_path = Path("/path/to/file.mp4")

        assert is_mxf_file(mxf_path)
        assert is_mxf_file(mxf_upper_path)  # Should handle uppercase
        assert not is_mxf_file(other_path)

    def test_should_ignore_file(self):
        """Test file ignoring logic."""
        test_file = Path("/path/to/test_file.mxf")
        hidden_file = Path("/path/to/.hidden.mxf")
        normal_file = Path("/path/to/normal.mxf")

        assert should_ignore_file(test_file)
        assert should_ignore_file(hidden_file)
        assert not should_ignore_file(normal_file)




class TestFileMetadataFunction:
    """Test the get_file_metadata function that replaced FileMetadata."""

    @pytest.mark.asyncio
    async def test_get_file_metadata_success(self):
        """Test successful file metadata retrieval."""
        with (
            patch("aiofiles.os.path.exists", new_callable=AsyncMock) as mock_exists,
            patch("aiofiles.os.stat", new_callable=AsyncMock) as mock_stat,
        ):
            mock_exists.return_value = True
            mock_stat.return_value.st_size = 1024
            mock_stat.return_value.st_mtime = 1609459200  # 2021-01-01

            metadata = await get_file_metadata("/test.mxf")

            assert metadata is not None
            assert metadata['size'] == 1024
            assert metadata['path'].name == "test.mxf"  # Platform-independent
            assert isinstance(metadata['path'], Path)
            assert metadata['last_write_time'] == datetime.fromtimestamp(1609459200)

    @pytest.mark.asyncio
    async def test_get_file_metadata_file_not_exists(self):
        """Test metadata retrieval when file doesn't exist."""
        with patch("aiofiles.os.path.exists", new_callable=AsyncMock) as mock_exists:
            mock_exists.return_value = False

            metadata = await get_file_metadata("/nonexistent.mxf")
            assert metadata is None

    @pytest.mark.asyncio
    async def test_get_file_metadata_os_error(self):
        """Test metadata retrieval handles OS errors gracefully."""
        with (
            patch("aiofiles.os.path.exists", new_callable=AsyncMock) as mock_exists,
            patch("aiofiles.os.stat", new_callable=AsyncMock) as mock_stat,
        ):
            mock_exists.return_value = True
            mock_stat.side_effect = OSError("Permission denied")

            metadata = await get_file_metadata("/test.mxf")
            assert metadata is None


class TestScanConfiguration:
    """Test the ScanConfiguration data class."""

    def test_creation(self):
        config = ScanConfiguration(
            source_directory="test_source",
            polling_interval_seconds=10,
            file_stable_time_seconds=120,
            enable_growing_file_support=False,
            growing_file_min_size_mb=100,
            keep_files_hours=336,
        )

        assert config.source_directory == "test_source"
        assert config.polling_interval_seconds == 10
        assert config.file_stable_time_seconds == 120
        assert config.enable_growing_file_support is False
        assert config.growing_file_min_size_mb == 100
        assert config.keep_files_hours == 336
