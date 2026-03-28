"""Tests for GrowingFileDetector — growth checking, status determination."""
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.domains.file_discovery.growing_file_detector import GrowingFileDetector
from app.models import TrackedFile, FileStatus


def _settings():
    s = MagicMock()
    s.growing_file_min_size_mb = 50
    s.growing_file_poll_interval_seconds = 5
    s.growing_file_growth_timeout_seconds = 30
    return s


def _tf(status=FileStatus.DISCOVERED, size=1000, **kw):
    defaults = dict(
        file_path="/src/test.mxf",
        file_size=size,
        status=status,
        last_growth_check=None,
    )
    defaults.update(kw)
    return TrackedFile(**defaults)


@pytest.fixture
def cmd_bus():
    return AsyncMock()


@pytest.fixture
def query_bus():
    return AsyncMock()


@pytest.fixture
def detector(cmd_bus, query_bus):
    return GrowingFileDetector(
        settings=_settings(),
        command_bus=cmd_bus,
        query_bus=query_bus,
    )


# ── Skipped states ──────────────────────────────────────────────

class TestSkippedStates:
    """Files in certain states should be returned as-is without I/O."""

    @pytest.mark.asyncio
    async def test_waiting_for_network_skipped(self, detector):
        tf = _tf(status=FileStatus.WAITING_FOR_NETWORK)
        result = await detector.check_file_growth_status(tf)
        assert result == FileStatus.WAITING_FOR_NETWORK

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [
        FileStatus.IN_QUEUE,
        FileStatus.COPYING,
        FileStatus.GROWING_COPY,
        FileStatus.COMPLETED,
        FileStatus.FAILED,
        FileStatus.REMOVED,
        FileStatus.SPACE_ERROR,
    ])
    async def test_copy_processing_states_skipped(self, detector, status):
        tf = _tf(status=status)
        result = await detector.check_file_growth_status(tf)
        assert result == status


# ── First check (no last_growth_check) ──────────────────────────

class TestFirstCheck:
    @pytest.mark.asyncio
    async def test_first_check_returns_discovered(self, detector, cmd_bus):
        tf = _tf(last_growth_check=None)

        with patch("aiofiles.os.path.getsize", return_value=5000):
            result = await detector.check_file_growth_status(tf)

        assert result == FileStatus.DISCOVERED
        cmd_bus.execute.assert_awaited_once()


# ── Subsequent checks ───────────────────────────────────────────

class TestSubsequentChecks:
    @pytest.mark.asyncio
    async def test_file_still_growing_returns_growing(self, detector, cmd_bus):
        """File size changed since last check → GROWING."""
        tf = _tf(
            size=1000,
            last_growth_check=datetime.now() - timedelta(seconds=5),
            growth_stable_since=datetime.now(),
        )

        with patch("aiofiles.os.path.getsize", return_value=2000):  # Grew
            result = await detector.check_file_growth_status(tf)

        assert result == FileStatus.GROWING
        cmd_bus.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_file_growing_and_large_returns_ready_to_start_growing(self, detector, cmd_bus):
        """File still growing and above min_size → READY_TO_START_GROWING."""
        tf = _tf(
            size=100 * 1024 * 1024,  # 100 MB > 50 MB min
            last_growth_check=datetime.now() - timedelta(seconds=5),
            growth_stable_since=None,
        )

        # File grew from 100MB to 110MB
        with patch("aiofiles.os.path.getsize", return_value=110 * 1024 * 1024):
            result = await detector.check_file_growth_status(tf)

        assert result == FileStatus.READY_TO_START_GROWING

    @pytest.mark.asyncio
    async def test_file_stable_and_small_returns_ready(self, detector, cmd_bus):
        """File unchanged and below min_size → READY (normal copy)."""
        tf = _tf(
            size=1000,
            last_growth_check=datetime.now() - timedelta(seconds=5),
            growth_stable_since=datetime.now() - timedelta(seconds=60),
        )

        with patch("aiofiles.os.path.getsize", return_value=1000):
            result = await detector.check_file_growth_status(tf)

        assert result == FileStatus.READY

    @pytest.mark.asyncio
    async def test_growing_status_only_applies_to_discovered_or_growing(self, detector, cmd_bus):
        """If status is WAITING_FOR_SPACE and analyzer returns GROWING, keep current."""
        tf = _tf(
            status=FileStatus.WAITING_FOR_SPACE,
            size=1000,
            last_growth_check=datetime.now() - timedelta(seconds=5),
            growth_stable_since=datetime.now(),
        )

        with patch("aiofiles.os.path.getsize", return_value=2000):
            result = await detector.check_file_growth_status(tf)

        # Should keep WAITING_FOR_SPACE, not go to GROWING
        assert result == FileStatus.WAITING_FOR_SPACE


# ── Error handling ──────────────────────────────────────────────

class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_file_not_found_returns_removed(self, detector):
        tf = _tf(last_growth_check=datetime.now())

        with patch("aiofiles.os.path.getsize", side_effect=FileNotFoundError):
            result = await detector.check_file_growth_status(tf)

        assert result == FileStatus.REMOVED

    @pytest.mark.asyncio
    async def test_generic_error_returns_failed(self, detector):
        tf = _tf(last_growth_check=datetime.now())

        with patch("aiofiles.os.path.getsize", side_effect=OSError("disk error")):
            result = await detector.check_file_growth_status(tf)

        assert result == FileStatus.FAILED


# ── Monitoring lifecycle ────────────────────────────────────────

class TestMonitoringLifecycle:
    @pytest.mark.asyncio
    async def test_start_monitoring(self, detector):
        await detector.start_monitoring()
        assert detector._monitoring_active is True

    @pytest.mark.asyncio
    async def test_start_monitoring_already_active(self, detector):
        detector._monitoring_active = True
        await detector.start_monitoring()  # Should not raise

    @pytest.mark.asyncio
    async def test_stop_monitoring(self, detector):
        detector._monitoring_active = True
        await detector.stop_monitoring()
        assert detector._monitoring_active is False
