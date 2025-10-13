"""
Tests for FileDiscoveryService - focused on file discovery operations only.
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from pathlib import Path
from app.services.scanner.file_discovery_service import FileDiscoveryService
from app.services.scanner.domain_objects import ScanConfiguration, FilePath


class TestFileDiscoveryService:
    """Test the FileDiscoveryService focused service."""

    @pytest.fixture
    def config(self):
        return ScanConfiguration(
            source_directory="/test/source",
            polling_interval_seconds=5,
            file_stable_time_seconds=30,
            enable_growing_file_support=False,
            growing_file_min_size_mb=100,
            keep_completed_files_hours=24,
            max_completed_files_in_memory=1000
        )

    @pytest.fixture
    def discovery_service(self, config):
        return FileDiscoveryService(config)

    @pytest.mark.asyncio
    async def test_discover_all_files_success(self, discovery_service):
        """Test successful file discovery."""
        with patch('aiofiles.os.path.exists', new_callable=AsyncMock) as mock_exists, \
             patch('aiofiles.os.path.isdir', new_callable=AsyncMock) as mock_isdir, \
             patch('os.walk') as mock_walk:

            mock_exists.return_value = True
            mock_isdir.return_value = True
            mock_walk.return_value = [
                ('/test/source', [], ['file1.mxf', 'file2.MXF', 'file3.mp4', 'test_file.mxf'])
            ]

            files = await discovery_service.discover_all_files()

            # Should find 2 files (excluding .mp4 and test_file)
            assert len(files) == 2
            file_paths = {f.path for f in files}
            assert any('file1.mxf' in path for path in file_paths)
            assert any('file2.MXF' in path for path in file_paths)

    @pytest.mark.asyncio
    async def test_discover_source_not_exists(self, discovery_service):
        """Test when source directory doesn't exist."""
        with patch('aiofiles.os.path.exists', new_callable=AsyncMock) as mock_exists:
            mock_exists.return_value = False

            files = await discovery_service.discover_all_files()
            assert len(files) == 0

    @pytest.mark.asyncio
    async def test_discover_source_not_directory(self, discovery_service):
        """Test when source path is not a directory."""
        with patch('aiofiles.os.path.exists', new_callable=AsyncMock) as mock_exists, \
             patch('aiofiles.os.path.isdir', new_callable=AsyncMock) as mock_isdir:

            mock_exists.return_value = True
            mock_isdir.return_value = False

            files = await discovery_service.discover_all_files()
            assert len(files) == 0

    @pytest.mark.asyncio
    async def test_discover_handles_exception(self, discovery_service):
        """Test that exceptions are handled gracefully."""
        with patch('aiofiles.os.path.exists', new_callable=AsyncMock) as mock_exists:
            mock_exists.side_effect = Exception("Test error")

            files = await discovery_service.discover_all_files()
            assert len(files) == 0  # Should return empty set on error

    @pytest.mark.asyncio
    async def test_filters_ignored_files(self, discovery_service):
        """Test that ignored files are filtered out."""
        with patch('aiofiles.os.path.exists', new_callable=AsyncMock) as mock_exists, \
             patch('aiofiles.os.path.isdir', new_callable=AsyncMock) as mock_isdir, \
             patch('os.walk') as mock_walk:

            mock_exists.return_value = True
            mock_isdir.return_value = True
            mock_walk.return_value = [
                ('/test/source', [], [
                    'normal.mxf',           # Should be included
                    'test_file.mxf',        # Should be filtered out
                    '.hidden.mxf',          # Should be filtered out
                    'another.mp4'           # Should be filtered out (not MXF)
                ])
            ]

            files = await discovery_service.discover_all_files()

            assert len(files) == 1
            file_paths = {f.path for f in files}
            assert any('normal.mxf' in path for path in file_paths)
