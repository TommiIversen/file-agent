"""Extra tests for _perform_directory_scan edge cases to push coverage above threshold."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from app.config import Settings
from app.domains.directory_browsing.models import DirectoryItem, DirectoryScanResult
from app.domains.directory_browsing.service import DirectoryScannerService


@pytest.fixture
def scanner():
    settings = MagicMock(spec=Settings)
    settings.source_directory = "/test/source"
    settings.destination_directory = "/test/dest"
    return DirectoryScannerService(settings, scan_timeout=1.0, item_timeout=0.5)


class TestPerformDirectoryScanEdgeCases:
    """Cover uncovered branches in _perform_directory_scan to reduce CRAP."""

    async def test_exists_check_timeout(self, scanner):
        """Branch: aiofiles.os.path.exists times out."""
        async def slow_exists(path):
            await asyncio.sleep(10)
            return True

        with patch("aiofiles.os.path.exists", new_callable=AsyncMock, side_effect=slow_exists):
            result = await scanner._perform_directory_scan("/test/path")

        assert not result.is_accessible
        assert "timed out" in result.error_message.lower()

    async def test_isdir_check_timeout(self, scanner):
        """Branch: path.exists succeeds but isdir times out."""
        async def slow_isdir(path):
            await asyncio.sleep(10)
            return True

        with (
            patch("aiofiles.os.path.exists", new_callable=AsyncMock, return_value=True),
            patch("aiofiles.os.path.isdir", new_callable=AsyncMock, side_effect=slow_isdir),
        ):
            result = await scanner._perform_directory_scan("/test/path")

        assert not result.is_accessible
        assert "timed out" in result.error_message.lower()

    async def test_listdir_timeout(self, scanner):
        """Branch: directory listing times out."""
        async def slow_listdir(path):
            await asyncio.sleep(10)
            return []

        with (
            patch("aiofiles.os.path.exists", new_callable=AsyncMock, return_value=True),
            patch("aiofiles.os.path.isdir", new_callable=AsyncMock, return_value=True),
            patch("aiofiles.os.listdir", new_callable=AsyncMock, side_effect=slow_listdir),
        ):
            result = await scanner._perform_directory_scan("/test/path")

        assert not result.is_accessible
        assert "timed out" in result.error_message.lower()

    async def test_listdir_permission_error(self, scanner):
        """Branch: listdir raises generic exception."""
        with (
            patch("aiofiles.os.path.exists", new_callable=AsyncMock, return_value=True),
            patch("aiofiles.os.path.isdir", new_callable=AsyncMock, return_value=True),
            patch("aiofiles.os.listdir", new_callable=AsyncMock, side_effect=PermissionError("denied")),
        ):
            result = await scanner._perform_directory_scan("/test/path")

        assert not result.is_accessible
        assert "denied" in result.error_message

    async def test_metadata_timeout_creates_basic_item(self, scanner):
        """Branch: individual item metadata times out -> creates basic item."""
        async def slow_stat(path):
            await asyncio.sleep(10)

        with (
            patch("aiofiles.os.path.exists", new_callable=AsyncMock, return_value=True),
            patch("aiofiles.os.path.isdir", new_callable=AsyncMock, return_value=True),
            patch("aiofiles.os.listdir", new_callable=AsyncMock, return_value=["slow_file.txt"]),
            patch("aiofiles.os.stat", new_callable=AsyncMock, side_effect=slow_stat),
        ):
            result = await scanner._perform_directory_scan("/test/path", recursive=False)

        assert result.is_accessible
        assert len(result.items) == 1
        assert result.items[0].name == "slow_file.txt"
        assert result.items[0].is_directory is False  # Default assumption

    async def test_metadata_exception_skips_item(self, scanner):
        """Branch: generic exception in metadata -> item is skipped."""
        with (
            patch("aiofiles.os.path.exists", new_callable=AsyncMock, return_value=True),
            patch("aiofiles.os.path.isdir", new_callable=AsyncMock, return_value=True),
            patch("aiofiles.os.listdir", new_callable=AsyncMock, return_value=["bad.txt"]),
            patch("aiofiles.os.stat", new_callable=AsyncMock, side_effect=OSError("I/O error")),
        ):
            result = await scanner._perform_directory_scan("/test/path", recursive=False)

        assert result.is_accessible
        # OSError in _get_item_metadata returns None, which is not a DirectoryItem
        # so it hits the "continue" branch

    async def test_recursive_subdirectory_timeout(self, scanner):
        """Branch: recursive scan of subdirectory times out."""
        def stat_result(path):
            s = MagicMock()
            s.st_ctime = 1640995200
            s.st_mtime = 1640995200
            if "subdir" in str(path):
                s.st_mode = 0o040755  # directory
                s.st_size = 0
            else:
                s.st_mode = 0o100644  # file
                s.st_size = 1024
            return s

        call_count = 0

        async def listdir_side_effect(path):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ["subdir"]
            # Recursive call: hang forever
            await asyncio.sleep(10)
            return []

        with (
            patch("aiofiles.os.path.exists", new_callable=AsyncMock, return_value=True),
            patch("aiofiles.os.path.isdir", new_callable=AsyncMock, return_value=True),
            patch("aiofiles.os.listdir", new_callable=AsyncMock, side_effect=listdir_side_effect),
            patch("aiofiles.os.stat", new_callable=AsyncMock, side_effect=stat_result),
        ):
            result = await scanner._perform_directory_scan("/test/path", recursive=True, max_depth=2)

        assert result.is_accessible
        # subdir found but recursive scan timed out — subdir item still in list
        assert any(item.name == "subdir" for item in result.items)

    async def test_recursive_subdirectory_exception(self, scanner):
        """Branch: recursive scan of subdirectory raises exception."""
        def stat_result(path):
            s = MagicMock()
            s.st_ctime = 1640995200
            s.st_mtime = 1640995200
            if "subdir" in str(path):
                s.st_mode = 0o040755
                s.st_size = 0
            else:
                s.st_mode = 0o100644
                s.st_size = 1024
            return s

        call_count = 0

        async def listdir_side_effect(path):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ["subdir"]
            raise PermissionError("no access")

        with (
            patch("aiofiles.os.path.exists", new_callable=AsyncMock, return_value=True),
            patch("aiofiles.os.path.isdir", new_callable=AsyncMock, return_value=True),
            patch("aiofiles.os.listdir", new_callable=AsyncMock, side_effect=listdir_side_effect),
            patch("aiofiles.os.stat", new_callable=AsyncMock, side_effect=stat_result),
        ):
            result = await scanner._perform_directory_scan("/test/path", recursive=True, max_depth=2)

        assert result.is_accessible

    async def test_empty_directory(self, scanner):
        """Branch: empty directory returns accessible result with no items."""
        with (
            patch("aiofiles.os.path.exists", new_callable=AsyncMock, return_value=True),
            patch("aiofiles.os.path.isdir", new_callable=AsyncMock, return_value=True),
            patch("aiofiles.os.listdir", new_callable=AsyncMock, return_value=[]),
        ):
            result = await scanner._perform_directory_scan("/test/path", recursive=False)

        assert result.is_accessible
        assert result.total_items == 0

    async def test_hidden_subdirs_not_scanned_recursively(self, scanner):
        """Branch: hidden directories are excluded from recursive scanning."""
        def stat_result(path):
            s = MagicMock()
            s.st_ctime = 1640995200
            s.st_mtime = 1640995200
            if ".hidden" in str(path):
                s.st_mode = 0o040755  # directory
                s.st_size = 0
            else:
                s.st_mode = 0o100644
                s.st_size = 100
            return s

        with (
            patch("aiofiles.os.path.exists", new_callable=AsyncMock, return_value=True),
            patch("aiofiles.os.path.isdir", new_callable=AsyncMock, return_value=True),
            patch("aiofiles.os.listdir", new_callable=AsyncMock, return_value=[".hidden_dir"]),
            patch("aiofiles.os.stat", new_callable=AsyncMock, side_effect=stat_result),
        ):
            result = await scanner._perform_directory_scan("/test/path", recursive=True, max_depth=3)

        assert result.is_accessible
        # .hidden_dir should appear in items but not be recursively scanned
        assert len(result.items) == 1
        assert result.items[0].is_hidden is True
