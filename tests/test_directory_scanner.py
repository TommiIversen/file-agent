"""
Test for Directory Scanner Service - Verification of SRP compliance and functionality.

Tests both the service layer and API endpoints for directory scanning.
"""

import asyncio
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.directory_scanner import (
    DirectoryScannerService,
    DirectoryScanResult,
    DirectoryItem
)
from app.config import Settings


class TestDirectoryScannerService:
    """Test the DirectoryScannerService SRP compliance and functionality."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings for testing."""
        settings = MagicMock(spec=Settings)
        settings.source_directory = "/test/source"
        settings.destination_directory = "/test/destination"
        return settings

    @pytest.fixture
    def scanner_service(self, mock_settings):
        """Create scanner service with mock settings."""
        return DirectoryScannerService(mock_settings)

    @pytest.mark.asyncio
    async def test_scanner_service_initialization(self, scanner_service, mock_settings):
        """Test that service initializes properly with SRP compliance."""
        assert scanner_service._settings == mock_settings
        assert scanner_service._scan_timeout == 30.0
        assert scanner_service._item_timeout == 5.0

    @pytest.mark.asyncio
    async def test_get_service_info(self, scanner_service):
        """Test service info returns proper configuration."""
        info = scanner_service.get_service_info()
        
        assert info["service"] == "DirectoryScannerService"
        assert info["scan_timeout_seconds"] == 30.0
        assert info["item_timeout_seconds"] == 5.0
        assert info["source_directory"] == "/test/source"
        assert info["destination_directory"] == "/test/destination"

    @pytest.mark.asyncio
    async def test_directory_not_exists(self, scanner_service):
        """Test handling of non-existent directory."""
        with patch('aiofiles.os.path.exists', new_callable=AsyncMock) as mock_exists:
            mock_exists.return_value = False
            
            result = await scanner_service.scan_custom_directory("/nonexistent/path")
            
            assert isinstance(result, DirectoryScanResult)
            assert not result.is_accessible
            assert result.error_message == "Directory does not exist"
            assert result.total_items == 0

    @pytest.mark.asyncio
    async def test_path_is_not_directory(self, scanner_service):
        """Test handling when path exists but is not a directory."""
        with patch('aiofiles.os.path.exists', new_callable=AsyncMock) as mock_exists, \
             patch('aiofiles.os.path.isdir', new_callable=AsyncMock) as mock_isdir:
            
            mock_exists.return_value = True
            mock_isdir.return_value = False
            
            result = await scanner_service.scan_custom_directory("/test/file.txt")
            
            assert not result.is_accessible
            assert result.error_message == "Path is not a directory"

    @pytest.mark.asyncio
    async def test_successful_directory_scan(self, scanner_service):
        """Test successful directory scan with mixed files and directories."""
        with patch('aiofiles.os.path.exists', new_callable=AsyncMock) as mock_exists, \
             patch('aiofiles.os.path.isdir', new_callable=AsyncMock) as mock_isdir, \
             patch('aiofiles.os.listdir', new_callable=AsyncMock) as mock_listdir, \
             patch('aiofiles.os.stat', new_callable=AsyncMock) as mock_stat:
            
            # Setup mocks for successful scan
            mock_exists.return_value = True
            mock_isdir.side_effect = lambda path: path.endswith("/test/dir") or path == "/test/path"
            mock_listdir.return_value = ["file1.txt", "file2.mxv", ".hidden", "subdir"]
            
            # Mock stat results
            mock_stat_result = MagicMock()
            mock_stat_result.st_size = 1024
            mock_stat_result.st_ctime = 1640995200  # 2022-01-01
            mock_stat_result.st_mtime = 1640995200  # 2022-01-01
            mock_stat.return_value = mock_stat_result
            
            result = await scanner_service.scan_custom_directory("/test/path")
            
            assert result.is_accessible
            assert result.total_items == 4
            assert len(result.items) == 4
            assert result.scan_duration_seconds > 0
            assert result.error_message is None

    @pytest.mark.asyncio
    async def test_scan_timeout_handling(self, scanner_service):
        """Test that scan timeout is handled gracefully."""
        async def slow_operation(path):
            """Mock function that takes too long to respond."""
            await asyncio.sleep(10)  # Longer than 5s item timeout
            return True
            
        with patch('aiofiles.os.path.exists', new_callable=AsyncMock) as mock_exists:
            # Make the exists call hang to trigger timeout
            mock_exists.side_effect = slow_operation
            
            result = await scanner_service.scan_custom_directory("/test/path")
            
            assert not result.is_accessible
            assert "timed out" in result.error_message.lower()
            assert result.scan_duration_seconds >= 5  # Item timeout, not scan timeout

    @pytest.mark.asyncio
    async def test_source_directory_scan(self, scanner_service):
        """Test scanning of configured source directory."""
        with patch.object(scanner_service, '_scan_directory', new_callable=AsyncMock) as mock_scan:
            expected_result = DirectoryScanResult(path="/test/source", is_accessible=True)
            mock_scan.return_value = expected_result
            
            result = await scanner_service.scan_source_directory(recursive=True, max_depth=2)
            
            mock_scan.assert_called_once_with(
                "/test/source", 
                description="source", 
                recursive=True, 
                max_depth=2
            )
            assert result == expected_result

    @pytest.mark.asyncio
    async def test_destination_directory_scan(self, scanner_service):
        """Test scanning of configured destination directory."""
        with patch.object(scanner_service, '_scan_directory', new_callable=AsyncMock) as mock_scan:
            expected_result = DirectoryScanResult(path="/test/destination", is_accessible=True)
            mock_scan.return_value = expected_result
            
            result = await scanner_service.scan_destination_directory(recursive=False, max_depth=1)
            
            mock_scan.assert_called_once_with(
                "/test/destination", 
                description="destination", 
                recursive=False, 
                max_depth=1
            )
            assert result == expected_result

    @pytest.mark.asyncio
    async def test_directory_item_metadata(self, scanner_service):
        """Test metadata collection for individual directory items."""
        with patch('aiofiles.os.path.isdir', new_callable=AsyncMock) as mock_isdir, \
             patch('aiofiles.os.stat', new_callable=AsyncMock) as mock_stat:
            
            # Test file item
            mock_isdir.return_value = False
            mock_stat_result = MagicMock()
            mock_stat_result.st_size = 2048
            mock_stat_result.st_ctime = 1640995200
            mock_stat_result.st_mtime = 1641081600
            mock_stat.return_value = mock_stat_result
            
            item = await scanner_service._get_item_metadata("/test", "example.mxv")
            
            assert item is not None
            assert item.name == "example.mxv"
            # Use Path for cross-platform path handling
            expected_path = str(Path("/test") / "example.mxv")
            assert item.path == expected_path
            assert not item.is_directory
            assert not item.is_hidden
            assert item.size_bytes == 2048
            assert item.created_time is not None
            assert item.modified_time is not None

    @pytest.mark.asyncio
    async def test_hidden_file_detection(self, scanner_service):
        """Test detection of hidden files (starting with .)."""
        with patch('aiofiles.os.path.isdir', new_callable=AsyncMock) as mock_isdir, \
             patch('aiofiles.os.stat', new_callable=AsyncMock) as mock_stat:
            
            mock_isdir.return_value = False
            mock_stat.return_value = MagicMock(st_size=100, st_ctime=1640995200, st_mtime=1640995200)
            
            item = await scanner_service._get_item_metadata("/test", ".hidden_file")
            
            assert item is not None
            assert item.is_hidden
            assert item.name == ".hidden_file"

    @pytest.mark.asyncio
    async def test_directory_item_no_size(self, scanner_service):
        """Test that directories don't have size_bytes set."""
        with patch('aiofiles.os.path.isdir', new_callable=AsyncMock) as mock_isdir, \
             patch('aiofiles.os.stat', new_callable=AsyncMock) as mock_stat:
            
            mock_isdir.return_value = True  # It's a directory
            mock_stat.return_value = MagicMock(st_ctime=1640995200, st_mtime=1640995200)
            
            item = await scanner_service._get_item_metadata("/test", "subdirectory")
            
            assert item is not None
            assert item.is_directory
            assert item.size_bytes is None  # Directories don't have size

    @pytest.mark.asyncio
    async def test_recursive_directory_scan(self, scanner_service):
        """Test recursive directory scanning."""
        with patch('aiofiles.os.path.exists', new_callable=AsyncMock) as mock_exists, \
             patch('aiofiles.os.path.isdir', new_callable=AsyncMock) as mock_isdir, \
             patch('aiofiles.os.listdir', new_callable=AsyncMock) as mock_listdir, \
             patch('aiofiles.os.stat', new_callable=AsyncMock) as mock_stat:
            
            # Setup mocks for successful recursive scan
            mock_exists.return_value = True
            
            # Mock directory structure: /test/path contains subdir1/
            def isdir_side_effect(path):
                return path in ["/test/path", str(Path("/test/path") / "subdir1")]
            
            mock_isdir.side_effect = isdir_side_effect
            
            def listdir_side_effect(path):
                if path == "/test/path":
                    return ["file1.txt", "subdir1"]
                elif str(path).endswith("subdir1"):
                    return ["file2.txt"]
                else:
                    return []
            
            mock_listdir.side_effect = listdir_side_effect
            
            # Mock stat results
            mock_stat_result = MagicMock()
            mock_stat_result.st_size = 1024
            mock_stat_result.st_ctime = 1640995200
            mock_stat_result.st_mtime = 1640995200
            mock_stat.return_value = mock_stat_result
            
            result = await scanner_service.scan_custom_directory(
                "/test/path", 
                recursive=True, 
                max_depth=2
            )
            
            assert result.is_accessible
            # Should find: file1.txt, subdir1/, file2.txt (from recursive scan)
            assert result.total_items == 3
            assert result.total_files == 2  # file1.txt, file2.txt
            assert result.total_directories == 1  # subdir1

    @pytest.mark.asyncio
    async def test_max_depth_limit(self, scanner_service):
        """Test that max depth limit is respected."""
        result = await scanner_service._perform_directory_scan(
            "/test/path", 
            recursive=True, 
            max_depth=2, 
            current_depth=3  # Exceeds max_depth
        )
        
        assert not result.is_accessible
        assert "Maximum scan depth" in result.error_message

    @pytest.mark.asyncio
    async def test_hierarchy_fields_in_items(self, scanner_service):
        """Test that hierarchy fields are properly set in directory items."""
        with patch('aiofiles.os.path.exists', new_callable=AsyncMock) as mock_exists, \
             patch('aiofiles.os.path.isdir', new_callable=AsyncMock) as mock_isdir, \
             patch('aiofiles.os.listdir', new_callable=AsyncMock) as mock_listdir, \
             patch('aiofiles.os.stat', new_callable=AsyncMock) as mock_stat:
            
            # Setup mocks for hierarchy test
            mock_exists.return_value = True
            mock_isdir.side_effect = lambda path: path == "/test/path"
            mock_listdir.return_value = ["file1.txt", "file2.mxv"]
            
            mock_stat_result = MagicMock()
            mock_stat_result.st_size = 1024
            mock_stat_result.st_ctime = 1640995200
            mock_stat_result.st_mtime = 1640995200
            mock_stat.return_value = mock_stat_result
            
            result = await scanner_service.scan_custom_directory("/test/path", recursive=False)
            
            assert result.is_accessible
            assert len(result.items) == 2
            
            # Check hierarchy fields
            for item in result.items:
                assert item.parent_path == "/test/path"
                assert item.depth_level == 0  # Root level
                assert item.relative_path == item.name  # Should be just the filename at root


class TestDirectoryScanResult:
    """Test DirectoryScanResult model functionality."""

    def test_directory_scan_result_auto_totals(self):
        """Test that totals are automatically calculated from items."""
        items = [
            DirectoryItem(name="file1.txt", path="/test/file1.txt", is_directory=False),
            DirectoryItem(name="file2.mxv", path="/test/file2.mxv", is_directory=False),
            DirectoryItem(name="subdir", path="/test/subdir", is_directory=True),
        ]
        
        result = DirectoryScanResult(
            path="/test",
            is_accessible=True,
            items=items
        )
        
        assert result.total_items == 3
        assert result.total_files == 2
        assert result.total_directories == 1

    def test_directory_scan_result_empty(self):
        """Test empty scan result."""
        result = DirectoryScanResult(
            path="/empty",
            is_accessible=True
        )
        
        assert result.total_items == 0
        assert result.total_files == 0
        assert result.total_directories == 0
        assert len(result.items) == 0


class TestDirectoryItem:
    """Test DirectoryItem model functionality."""

    def test_directory_item_creation(self):
        """Test basic DirectoryItem creation."""
        item = DirectoryItem(
            name="test.mxv",
            path="/test/test.mxv",
            is_directory=False,
            size_bytes=1024,
            created_time=datetime(2022, 1, 1, 12, 0, 0)
        )
        
        assert item.name == "test.mxv"
        assert item.path == "/test/test.mxv"
        assert not item.is_directory
        assert not item.is_hidden  # Default value
        assert item.size_bytes == 1024

    def test_directory_item_hidden_flag(self):
        """Test hidden flag detection."""
        item = DirectoryItem(
            name=".hidden",
            path="/test/.hidden",
            is_directory=False,
            is_hidden=True
        )
        
        assert item.is_hidden

    def test_directory_item_json_encoding(self):
        """Test JSON encoding of datetime fields."""
        item = DirectoryItem(
            name="test.txt",
            path="/test/test.txt",
            is_directory=False,
            created_time=datetime(2022, 1, 1, 12, 0, 0)
        )
        
        # Test that model can be converted to dict (FastAPI compatibility)
        item_dict = item.model_dump()
        assert "created_time" in item_dict
        
        # Test JSON serialization
        item_json = item.model_dump_json()
        assert '"created_time":"2022-01-01T12:00:00"' in item_json


if __name__ == "__main__":
    pytest.main([__file__, "-v"])