"""Tests for StorageChecker — accessibility, disk usage, write access."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

from app.domains.storage.storage_checker import StorageChecker, StorageAccessError
from app.models import StorageStatus


@pytest.fixture
def checker():
    return StorageChecker(test_file_prefix=".test_", io_timeout=0.05, network_io_timeout=0.1)


# ── check_path (integration of sub-methods) ─────────────────────

class TestCheckPath:
    @pytest.mark.asyncio
    async def test_accessible_path_returns_ok(self, checker):
        with patch.object(checker, "_check_accessibility", return_value=True), \
             patch.object(checker, "_get_disk_usage", return_value=(100.0, 500.0, 400.0)), \
             patch.object(checker, "_check_write_access", return_value=True):
            info = await checker.check_path("/dest", 50.0, 10.0)

        assert info.is_accessible is True
        assert info.has_write_access is True
        assert info.free_space_gb == 100.0
        assert info.status == StorageStatus.OK
        assert info.error_message is None

    @pytest.mark.asyncio
    async def test_inaccessible_path_returns_error(self, checker):
        with patch.object(checker, "_check_accessibility", return_value=False):
            info = await checker.check_path("/gone", 50.0, 10.0)

        assert info.is_accessible is False
        assert info.status == StorageStatus.ERROR
        assert info.error_message is not None

    @pytest.mark.asyncio
    async def test_low_space_returns_warning(self, checker):
        with patch.object(checker, "_check_accessibility", return_value=True), \
             patch.object(checker, "_get_disk_usage", return_value=(30.0, 500.0, 470.0)), \
             patch.object(checker, "_check_write_access", return_value=True):
            info = await checker.check_path("/dest", 50.0, 10.0)

        assert info.status == StorageStatus.WARNING

    @pytest.mark.asyncio
    async def test_critical_space_returns_critical(self, checker):
        with patch.object(checker, "_check_accessibility", return_value=True), \
             patch.object(checker, "_get_disk_usage", return_value=(5.0, 500.0, 495.0)), \
             patch.object(checker, "_check_write_access", return_value=True):
            info = await checker.check_path("/dest", 50.0, 10.0)

        assert info.status == StorageStatus.CRITICAL

    @pytest.mark.asyncio
    async def test_exception_during_check_returns_error(self, checker):
        with patch.object(checker, "_check_accessibility", side_effect=RuntimeError("boom")):
            info = await checker.check_path("/fail", 50.0, 10.0)

        assert info.is_accessible is False
        assert info.error_message is not None

    @pytest.mark.asyncio
    async def test_no_write_access_sets_error_message(self, checker):
        """When accessible but no write access, error_message should be populated."""
        with patch.object(checker, "_check_accessibility", return_value=True), \
             patch.object(checker, "_get_disk_usage", return_value=(100.0, 500.0, 400.0)), \
             patch.object(checker, "_check_write_access", return_value=False):
            info = await checker.check_path("/dest", 50.0, 10.0)

        assert info.status == StorageStatus.CRITICAL
        assert info.error_message == "No write access"

    @pytest.mark.asyncio
    async def test_disk_usage_and_write_check_run_in_parallel(self, checker):
        """Verify _get_disk_usage and _check_write_access are called (parallel via gather)."""
        disk_mock = AsyncMock(return_value=(100.0, 500.0, 400.0))
        write_mock = AsyncMock(return_value=True)

        with patch.object(checker, "_check_accessibility", return_value=True), \
             patch.object(checker, "_get_disk_usage", disk_mock), \
             patch.object(checker, "_check_write_access", write_mock):
            info = await checker.check_path("/dest", 50.0, 10.0)

        disk_mock.assert_awaited_once()
        write_mock.assert_awaited_once()
        assert info.status == StorageStatus.OK


# ── _check_accessibility ─────────────────────────────────────────

class TestCheckAccessibility:
    @pytest.mark.asyncio
    async def test_existing_directory(self, checker):
        with patch("aiofiles.os.path.exists", return_value=True), \
             patch("aiofiles.os.path.isdir", return_value=True):
            assert await checker._check_accessibility("/dest") is True

    @pytest.mark.asyncio
    async def test_nonexistent_path(self, checker):
        with patch("aiofiles.os.path.exists", return_value=False):
            assert await checker._check_accessibility("/gone") is False

    @pytest.mark.asyncio
    async def test_timeout_returns_false(self, checker):
        async def slow_check(path):
            await asyncio.sleep(10)
            return True

        with patch("aiofiles.os.path.exists", side_effect=slow_check):
            result = await checker._check_accessibility("/slow")

        assert result is False


# ── _get_disk_usage ──────────────────────────────────────────────

class TestGetDiskUsage:
    @pytest.mark.asyncio
    async def test_returns_gb_values(self, checker):
        gb = 1024 ** 3
        mock_usage = (500 * gb, 400 * gb, 100 * gb)  # total, used, free

        with patch("shutil.disk_usage", return_value=mock_usage):
            free, total, used = await checker._get_disk_usage("/dest")

        assert abs(free - 100.0) < 0.01
        assert abs(total - 500.0) < 0.01
        assert abs(used - 400.0) < 0.01

    @pytest.mark.asyncio
    async def test_raises_on_error(self, checker):
        with patch("shutil.disk_usage", side_effect=OSError("disk error")):
            with pytest.raises(StorageAccessError):
                await checker._get_disk_usage("/fail")


# ── _check_write_access ─────────────────────────────────────────

class TestCheckWriteAccess:
    @pytest.mark.asyncio
    async def test_writable_returns_true(self, checker):
        with patch.object(checker, "_create_test_file", return_value="/dest/.test_abc.tmp"), \
             patch.object(checker, "_cleanup_test_file", return_value=None):
            assert await checker._check_write_access("/dest") is True

    @pytest.mark.asyncio
    async def test_not_writable_returns_false(self, checker):
        with patch.object(checker, "_create_test_file", side_effect=StorageAccessError("no write")), \
             patch.object(checker, "_cleanup_test_file", return_value=None):
            assert await checker._check_write_access("/dest") is False


# ── _get_timeout_for_path ────────────────────────────────────────────

class TestGetTimeoutForPath:
    def test_local_path_uses_io_timeout(self):
        checker = StorageChecker(io_timeout=5.0, network_io_timeout=10.0)
        assert checker._get_timeout_for_path("/local/path") == 5.0
        assert checker._get_timeout_for_path("C:\\data") == 5.0

    def test_unc_path_uses_network_timeout(self):
        checker = StorageChecker(io_timeout=5.0, network_io_timeout=10.0)
        assert checker._get_timeout_for_path("\\\\server\\share") == 10.0
        assert checker._get_timeout_for_path("//server/share") == 10.0


# ── cleanup_old_test_files ───────────────────────────────────────

class TestCleanupOldTestFiles:
    @pytest.mark.asyncio
    async def test_cleans_matching_files(self, checker):
        entry1 = MagicMock()
        entry1.is_file.return_value = True
        entry1.name = ".test_abc123.tmp"
        entry1.path = "/dest/.test_abc123.tmp"

        entry2 = MagicMock()
        entry2.is_file.return_value = True
        entry2.name = "normal_file.mxf"
        entry2.path = "/dest/normal_file.mxf"

        with patch("aiofiles.os.path.isdir", return_value=True), \
             patch("aiofiles.os.scandir", return_value=[entry1, entry2]), \
             patch("aiofiles.os.remove", return_value=None):
            count = await checker.cleanup_old_test_files("/dest")

        assert count == 1

    @pytest.mark.asyncio
    async def test_nonexistent_directory_returns_zero(self, checker):
        with patch("aiofiles.os.path.isdir", return_value=False):
            count = await checker.cleanup_old_test_files("/gone")
        assert count == 0


class TestCleanupAllTestFiles:
    @pytest.mark.asyncio
    async def test_cleans_both_directories(self, checker):
        with patch.object(checker, "cleanup_old_test_files", return_value=2), \
             patch("aiofiles.os.path.isdir", return_value=True):
            count = await checker.cleanup_all_test_files("/src", "/dest")
        assert count == 4  # 2 from source + 2 from dest

    @pytest.mark.asyncio
    async def test_source_only(self, checker):
        with patch.object(checker, "cleanup_old_test_files", return_value=1):
            count = await checker.cleanup_all_test_files("/src")
        assert count == 1
