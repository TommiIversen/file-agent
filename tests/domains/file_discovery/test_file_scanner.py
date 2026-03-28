"""Tests for FileScanner — pure functions, scanning lifecycle, and stability checks."""
import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.domains.file_discovery.file_scanner import (
    FileScanner,
    is_mxf_file,
    should_ignore_file,
    get_file_metadata,
)
from app.domains.file_discovery.domain_objects import ScanConfiguration
from app.models import FileStatus


def _config(**overrides):
    defaults = dict(
        source_directory="/src",
        polling_interval_seconds=5,
        file_stable_time_seconds=10,
        keep_files_hours=24,
        growing_file_poll_interval_seconds=5,
        growing_file_safety_margin_mb=50,
        growing_file_growth_timeout_seconds=300,
        growing_file_chunk_size_kb=1024,
    )
    defaults.update(overrides)
    return ScanConfiguration(**defaults)


def _settings():
    s = MagicMock()
    s.growing_file_min_size_mb = 50
    s.growing_file_poll_interval_seconds = 5
    s.growing_file_growth_timeout_seconds = 300
    return s


# ── Pure function tests ─────────────────────────────────────────

class TestIsMxfFile:
    def test_mxf_extension(self):
        assert is_mxf_file(Path("/src/test.mxf")) is True

    def test_mxf_uppercase(self):
        assert is_mxf_file(Path("/src/test.MXF")) is True

    def test_non_mxf(self):
        assert is_mxf_file(Path("/src/test.mp4")) is False

    def test_no_extension(self):
        assert is_mxf_file(Path("/src/testfile")) is False


class TestShouldIgnoreFile:
    def test_test_file_ignored(self):
        assert should_ignore_file(Path("/src/test_file_001.mxf")) is True

    def test_dotfile_ignored(self):
        assert should_ignore_file(Path("/src/.hidden.mxf")) is True

    def test_normal_file_not_ignored(self):
        assert should_ignore_file(Path("/src/recording.mxf")) is False


class TestGetFileMetadata:
    @pytest.mark.asyncio
    async def test_returns_metadata_for_existing_file(self):
        mock_stat = MagicMock()
        mock_stat.st_size = 5000
        mock_stat.st_mtime = 1700000000.0
        mock_stat.st_ctime = 1699999000.0

        with patch("aiofiles.os.path.exists", return_value=True), \
             patch("aiofiles.os.stat", return_value=mock_stat):
            result = await get_file_metadata("/src/test.mxf")

        assert result is not None
        assert result["size"] == 5000
        assert result["path"] == Path("/src/test.mxf")

    @pytest.mark.asyncio
    async def test_returns_none_for_nonexistent_file(self):
        with patch("aiofiles.os.path.exists", return_value=False):
            result = await get_file_metadata("/src/gone.mxf")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_os_error(self):
        with patch("aiofiles.os.path.exists", side_effect=OSError("disk error")):
            result = await get_file_metadata("/src/broken.mxf")
        assert result is None


# ── Scanner lifecycle tests ─────────────────────────────────────

class TestScannerLifecycle:
    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        cmd_bus = AsyncMock()
        query_bus = AsyncMock()

        scanner = FileScanner(
            config=_config(),
            command_bus=cmd_bus,
            query_bus=query_bus,
            settings=_settings(),
        )

        assert scanner.is_scanning() is False
        assert scanner.is_paused() is False

        await scanner.start_scanning()
        assert scanner.is_scanning() is True

        await scanner.stop_scanning()
        assert scanner.is_scanning() is False
        assert scanner.is_paused() is True

    @pytest.mark.asyncio
    async def test_double_start_ignored(self):
        scanner = FileScanner(
            config=_config(),
            command_bus=AsyncMock(),
            query_bus=AsyncMock(),
            settings=_settings(),
        )
        await scanner.start_scanning()
        await scanner.start_scanning()  # Should log warning but not crash
        await scanner.stop_scanning()

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self):
        scanner = FileScanner(
            config=_config(),
            command_bus=AsyncMock(),
            query_bus=AsyncMock(),
            settings=_settings(),
        )
        await scanner.stop_scanning()  # Should not raise


# ── _discover_all_files ─────────────────────────────────────────

class TestDiscoverAllFiles:
    @pytest.mark.asyncio
    async def test_discovers_mxf_files(self):
        scanner = FileScanner(
            config=_config(source_directory="/src"),
            command_bus=AsyncMock(),
            query_bus=AsyncMock(),
            settings=_settings(),
        )

        walk_result = [("/src", [], ["rec1.mxf", "rec2.mxf", "readme.txt", ".hidden.mxf"])]

        with patch("aiofiles.os.path.exists", return_value=True), \
             patch("aiofiles.os.path.isdir", return_value=True), \
             patch("asyncio.to_thread", side_effect=[walk_result, "/src/rec1.mxf", "/src/rec2.mxf"]):
            result = await scanner._discover_all_files()

        # Should find rec1.mxf and rec2.mxf (not txt, not .hidden)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_nonexistent_source_returns_empty(self):
        scanner = FileScanner(
            config=_config(source_directory="/nonexistent"),
            command_bus=AsyncMock(),
            query_bus=AsyncMock(),
            settings=_settings(),
        )

        with patch("aiofiles.os.path.exists", return_value=False):
            result = await scanner._discover_all_files()

        assert len(result) == 0


# ── _check_file_stability ───────────────────────────────────────

class TestCheckFileStability:
    @pytest.mark.asyncio
    async def test_marks_file_ready(self):
        cmd_bus = AsyncMock()
        query_bus = AsyncMock()

        from app.models import TrackedFile
        tf = TrackedFile(
            file_path="/src/test.mxf",
            file_size=5000,
            status=FileStatus.DISCOVERED,
        )

        # Query bus returns one discovered file, no growing files
        query_bus.execute.side_effect = [[tf], []]

        scanner = FileScanner(
            config=_config(),
            command_bus=cmd_bus,
            query_bus=query_bus,
            settings=_settings(),
        )

        mock_stat = MagicMock()
        mock_stat.st_size = 5000
        mock_stat.st_mtime = 1700000000.0
        mock_stat.st_ctime = 1699999000.0

        # GrowingFileDetector returns READY
        with patch("aiofiles.os.path.exists", return_value=True), \
             patch("aiofiles.os.stat", return_value=mock_stat), \
             patch.object(scanner.growing_file_detector, "check_file_growth_status", return_value=FileStatus.READY):
            await scanner._check_file_stability()

        # Should have called MarkFileStableCommand
        cmd_bus.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_marks_file_growing(self):
        cmd_bus = AsyncMock()
        query_bus = AsyncMock()

        from app.models import TrackedFile
        tf = TrackedFile(
            file_path="/src/test.mxf",
            file_size=5000,
            status=FileStatus.DISCOVERED,
        )

        query_bus.execute.side_effect = [[tf], []]

        scanner = FileScanner(
            config=_config(),
            command_bus=cmd_bus,
            query_bus=query_bus,
            settings=_settings(),
        )

        mock_stat = MagicMock()
        mock_stat.st_size = 10000
        mock_stat.st_mtime = 1700000000.0
        mock_stat.st_ctime = 1699999000.0

        with patch("aiofiles.os.path.exists", return_value=True), \
             patch("aiofiles.os.stat", return_value=mock_stat), \
             patch.object(scanner.growing_file_detector, "check_file_growth_status", return_value=FileStatus.GROWING):
            await scanner._check_file_stability()

        cmd_bus.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_discovered_to_ready_to_start_growing(self):
        """DISCOVERED → GROWING → READY_TO_START_GROWING (two-step transition)."""
        cmd_bus = AsyncMock()
        query_bus = AsyncMock()

        from app.models import TrackedFile
        tf = TrackedFile(
            file_path="/src/test.mxf",
            file_size=100_000_000,
            status=FileStatus.DISCOVERED,
        )

        query_bus.execute.side_effect = [[tf], []]

        scanner = FileScanner(
            config=_config(),
            command_bus=cmd_bus,
            query_bus=query_bus,
            settings=_settings(),
        )

        mock_stat = MagicMock()
        mock_stat.st_size = 110_000_000
        mock_stat.st_mtime = 1700000000.0
        mock_stat.st_ctime = 1699999000.0

        with patch("aiofiles.os.path.exists", return_value=True), \
             patch("aiofiles.os.stat", return_value=mock_stat), \
             patch.object(scanner.growing_file_detector, "check_file_growth_status",
                          return_value=FileStatus.READY_TO_START_GROWING):
            await scanner._check_file_stability()

        # Should have 2 commands: MarkFileGrowing then MarkFileReadyToStartGrowing
        assert cmd_bus.execute.await_count == 2


# ── _process_discovered_files ───────────────────────────────────

class TestProcessDiscoveredFiles:
    @pytest.mark.asyncio
    async def test_adds_new_file(self):
        cmd_bus = AsyncMock()
        query_bus = AsyncMock()

        # should_skip=False, no existing file
        query_bus.execute.side_effect = [False, None]

        scanner = FileScanner(
            config=_config(),
            command_bus=cmd_bus,
            query_bus=query_bus,
            settings=_settings(),
        )

        mock_stat = MagicMock()
        mock_stat.st_size = 5000
        mock_stat.st_mtime = 1700000000.0
        mock_stat.st_ctime = 1699999000.0

        with patch("aiofiles.os.path.exists", return_value=True), \
             patch("aiofiles.os.stat", return_value=mock_stat):
            await scanner._process_discovered_files({Path("/src/new.mxf")})

        cmd_bus.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_file_when_should_skip(self):
        cmd_bus = AsyncMock()
        query_bus = AsyncMock()

        query_bus.execute.return_value = True  # should_skip=True

        scanner = FileScanner(
            config=_config(),
            command_bus=cmd_bus,
            query_bus=query_bus,
            settings=_settings(),
        )

        await scanner._process_discovered_files({Path("/src/skip.mxf")})
        cmd_bus.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_empty_file(self):
        cmd_bus = AsyncMock()
        query_bus = AsyncMock()

        query_bus.execute.side_effect = [False, None]

        scanner = FileScanner(
            config=_config(),
            command_bus=cmd_bus,
            query_bus=query_bus,
            settings=_settings(),
        )

        mock_stat = MagicMock()
        mock_stat.st_size = 0  # Empty file
        mock_stat.st_mtime = 1700000000.0
        mock_stat.st_ctime = 1699999000.0

        with patch("aiofiles.os.path.exists", return_value=True), \
             patch("aiofiles.os.stat", return_value=mock_stat):
            await scanner._process_discovered_files({Path("/src/empty.mxf")})

        cmd_bus.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_existing_active_file(self):
        cmd_bus = AsyncMock()
        query_bus = AsyncMock()

        from app.models import TrackedFile
        existing = TrackedFile(file_path="/src/active.mxf", file_size=5000)
        # should_skip=False, existing_file=existing
        query_bus.execute.side_effect = [False, existing]

        scanner = FileScanner(
            config=_config(),
            command_bus=cmd_bus,
            query_bus=query_bus,
            settings=_settings(),
        )

        mock_stat = MagicMock()
        mock_stat.st_size = 5000
        mock_stat.st_mtime = 1700000000.0
        mock_stat.st_ctime = 1699999000.0

        with patch("aiofiles.os.path.exists", return_value=True), \
             patch("aiofiles.os.stat", return_value=mock_stat):
            await scanner._process_discovered_files({Path("/src/active.mxf")})

        cmd_bus.execute.assert_not_awaited()
