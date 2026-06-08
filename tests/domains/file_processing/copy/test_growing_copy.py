"""
Tests for GrowingFileCopyStrategy — the main copy orchestrator.

Test strategy:
- is_file_currently_growing: pure logic, zero mocks
- copy_file: mock _copy_growing_file for orchestration tests
- _copy_growing_file: real tmp_path files, only mock io_loop
- _growing_copy_loop: call directly with params, mock _get_file_size + io_loop
"""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.core.events.event_bus import DomainEventBus
from app.core.events.file_events import FileCopyCompletedEvent
from app.core.exceptions import InvalidTransitionError
from app.core.file_repository import FileRepository
from app.core.file_state_machine import FileStateMachine
from app.domains.file_processing.copy.copy_io_loop import CopyIoLoop
from app.domains.file_processing.copy.exceptions import (
    FileCopyError,
    FileCopyIntegrityError,
    FileCopyIOError,
    FileCopyTimeoutError,
)
from app.domains.file_processing.copy.file_verification import FileVerificationService
from app.domains.file_processing.copy.growing_copy import GrowingFileCopyStrategy
from app.domains.file_processing.copy.network_error_detector import NetworkError, NetworkErrorDetector
from app.models import FileStatus, TrackedFile


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def settings():
    s = Settings()
    s.growing_file_min_size_mb = 1  # 1MB for fast tests
    s.growing_file_safety_margin_mb = 1
    s.growing_file_mxf_safety_margin_mb = 1
    s.growing_file_poll_interval_seconds = 1
    s.growing_file_growth_timeout_seconds = 2
    s.growing_file_chunk_size_kb = 64
    s.growing_copy_pause_ms = 0
    s.file_operation_timeout_seconds = 1
    s.max_retry_attempts = 3
    return s


@pytest.fixture
def file_repository():
    return AsyncMock(spec=FileRepository)


@pytest.fixture
def event_bus():
    bus = AsyncMock(spec=DomainEventBus)
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def state_machine():
    return AsyncMock(spec=FileStateMachine)


@pytest.fixture
def verification_service():
    vs = AsyncMock(spec=FileVerificationService)
    vs.verify_integrity = AsyncMock(return_value=(True, 1000, 1000))
    vs.delete_source_file = AsyncMock(return_value=(True, None))
    return vs


@pytest.fixture
def io_loop():
    loop = AsyncMock(spec=CopyIoLoop)
    loop.copy_chunk_range = AsyncMock(return_value=(1000, 100, 0.0, AsyncMock()))
    return loop


@pytest.fixture
def strategy(settings, file_repository, event_bus, state_machine, verification_service, io_loop):
    return GrowingFileCopyStrategy(
        settings=settings,
        file_repository=file_repository,
        event_bus=event_bus,
        state_machine=state_machine,
        verification_service=verification_service,
        io_loop=io_loop,
    )


def _make_tracked_file(**overrides) -> TrackedFile:
    defaults = dict(
        file_path="/source/test.mxf",
        status=FileStatus.READY,
        file_size=5000,
        growth_rate_mbps=0.0,
    )
    defaults.update(overrides)
    return TrackedFile(**defaults)


# ---------------------------------------------------------------------------
# TestIsFileCurrentlyGrowing — pure logic, zero mocks
# ---------------------------------------------------------------------------

class TestIsFileCurrentlyGrowing:

    def test_growing_status_returns_true(self, strategy):
        tf = _make_tracked_file(status=FileStatus.GROWING)
        assert strategy.is_file_currently_growing(tf) is True

    def test_ready_to_start_growing_returns_true(self, strategy):
        tf = _make_tracked_file(status=FileStatus.READY_TO_START_GROWING)
        assert strategy.is_file_currently_growing(tf) is True

    def test_growing_copy_status_returns_true(self, strategy):
        tf = _make_tracked_file(status=FileStatus.GROWING_COPY)
        assert strategy.is_file_currently_growing(tf) is True

    def test_ready_with_growth_rate_returns_true(self, strategy):
        tf = _make_tracked_file(status=FileStatus.READY, growth_rate_mbps=2.5)
        assert strategy.is_file_currently_growing(tf) is True

    def test_ready_with_significant_size_increase_returns_true(self, strategy):
        tf = _make_tracked_file(
            status=FileStatus.READY,
            file_size=20_000_000,
            first_seen_size=10_000_000,  # 100% growth > 10%
        )
        assert strategy.is_file_currently_growing(tf) is True

    def test_ready_with_small_size_increase_returns_false(self, strategy):
        tf = _make_tracked_file(
            status=FileStatus.READY,
            file_size=10_050_000,
            first_seen_size=10_000_000,  # 0.5% growth < 10%, and < 1MB
        )
        assert strategy.is_file_currently_growing(tf) is False

    def test_ready_with_no_growth_returns_false(self, strategy):
        tf = _make_tracked_file(status=FileStatus.READY, growth_rate_mbps=0.0)
        assert strategy.is_file_currently_growing(tf) is False

    def test_copying_status_returns_false(self, strategy):
        tf = _make_tracked_file(status=FileStatus.COPYING)
        assert strategy.is_file_currently_growing(tf) is False

    def test_completed_status_returns_false(self, strategy):
        tf = _make_tracked_file(status=FileStatus.COMPLETED)
        assert strategy.is_file_currently_growing(tf) is False

    def test_failed_status_returns_false(self, strategy):
        tf = _make_tracked_file(status=FileStatus.FAILED)
        assert strategy.is_file_currently_growing(tf) is False

    def test_ready_over_1mb_increase_returns_true(self, strategy):
        """Even if % is small, >1MB absolute increase means growing."""
        tf = _make_tracked_file(
            status=FileStatus.READY,
            file_size=200_000_000,        # 200MB
            first_seen_size=198_500_000,  # 1.5MB growth, 0.75% → but >1MB
        )
        assert strategy.is_file_currently_growing(tf) is True


class TestSupportsFile:

    def test_always_returns_true(self, strategy):
        tf = _make_tracked_file()
        assert strategy.supports_file(tf) is True


class TestGetSafetyMarginBytes:

    def test_mxf_uses_mxf_specific_margin(self, strategy):
        strategy.settings.growing_file_safety_margin_mb = 10
        strategy.settings.growing_file_mxf_safety_margin_mb = 50

        assert strategy._get_safety_margin_bytes("/source/test.mxf") == 50 * 1024 * 1024

    def test_non_mxf_uses_default_margin(self, strategy):
        strategy.settings.growing_file_safety_margin_mb = 10
        strategy.settings.growing_file_mxf_safety_margin_mb = 50

        assert strategy._get_safety_margin_bytes("/source/test.wav") == 10 * 1024 * 1024


# ---------------------------------------------------------------------------
# TestGetFileSize
# ---------------------------------------------------------------------------

class TestGetFileSize:

    async def test_returns_file_size(self, strategy, tmp_path):
        f = tmp_path / "test.mxf"
        f.write_bytes(b"x" * 4096)
        size = await strategy._get_file_size(str(f))
        assert size == 4096

    async def test_nonexistent_file_raises_file_not_found_error(self, strategy, tmp_path):
        # FileNotFoundError must NOT be wrapped in FileCopyIOError so the
        # classifier can distinguish 'mount offline' from 'file truly deleted'.
        with pytest.raises(FileNotFoundError):
            await strategy._get_file_size(str(tmp_path / "no_such_file.mxf"))

    async def test_timeout_raises_timeout_error(self, strategy):
        with patch("aiofiles.os.path.getsize", new_callable=AsyncMock) as mock_gs:
            mock_gs.side_effect = asyncio.TimeoutError()
            with pytest.raises(FileCopyTimeoutError):
                await strategy._get_file_size("/fake/path")


# ---------------------------------------------------------------------------
# TestCopyFile — orchestration tests (mock _copy_growing_file)
# ---------------------------------------------------------------------------

class TestCopyFileStaticHappyPath:
    """Test the full copy_file flow for a static file that succeeds."""

    async def test_static_file_completes(self, strategy, tmp_path, state_machine, verification_service, event_bus):
        source = tmp_path / "source" / "test.mxf"
        source.parent.mkdir()
        source.write_bytes(b"x" * 2000)
        dest = tmp_path / "dest" / "test.mxf"

        tf = _make_tracked_file(file_path=str(source), file_size=2000)

        # Mock _copy_growing_file to return True (the copy "worked")
        strategy._copy_growing_file = AsyncMock(return_value=True)
        verification_service.verify_integrity.return_value = (True, 2000, 2000)
        verification_service.delete_source_file.return_value = (True, None)

        result = await strategy.copy_file(str(source), str(dest), tf)

        assert result is True
        state_machine.transition.assert_called_once()
        call_kwargs = state_machine.transition.call_args.kwargs
        assert call_kwargs["new_status"] == FileStatus.COMPLETED
        assert call_kwargs["copy_progress"] == 100.0
        event_bus.publish.assert_called_once()

    async def test_delete_source_fails_gives_completed_delete_failed(
        self, strategy, tmp_path, state_machine, verification_service
    ):
        source = tmp_path / "source" / "test.mxf"
        source.parent.mkdir()
        source.write_bytes(b"x" * 2000)
        dest = tmp_path / "dest" / "test.mxf"
        tf = _make_tracked_file(file_path=str(source), file_size=2000)

        strategy._copy_growing_file = AsyncMock(return_value=True)
        verification_service.verify_integrity.return_value = (True, 2000, 2000)
        verification_service.delete_source_file.return_value = (False, "file in use")

        result = await strategy.copy_file(str(source), str(dest), tf)

        assert result is True
        call_kwargs = state_machine.transition.call_args.kwargs
        assert call_kwargs["new_status"] == FileStatus.COMPLETED_DELETE_FAILED

    async def test_verification_fails_raises_integrity_error(
        self, strategy, tmp_path, verification_service
    ):
        source = tmp_path / "source" / "test.mxf"
        source.parent.mkdir()
        source.write_bytes(b"x" * 2000)
        dest = tmp_path / "dest" / "test.mxf"
        tf = _make_tracked_file(file_path=str(source), file_size=2000)

        strategy._copy_growing_file = AsyncMock(return_value=True)
        verification_service.verify_integrity.return_value = (False, 2000, 0)

        with pytest.raises(FileCopyIntegrityError):
            await strategy.copy_file(str(source), str(dest), tf)

    async def test_state_transition_fails_raises_copy_error(
        self, strategy, tmp_path, state_machine, verification_service
    ):
        source = tmp_path / "source" / "test.mxf"
        source.parent.mkdir()
        source.write_bytes(b"x" * 2000)
        dest = tmp_path / "dest" / "test.mxf"
        tf = _make_tracked_file(file_path=str(source), file_size=2000)

        strategy._copy_growing_file = AsyncMock(return_value=True)
        verification_service.verify_integrity.return_value = (True, 2000, 2000)
        verification_service.delete_source_file.return_value = (True, None)
        state_machine.transition.side_effect = InvalidTransitionError("test.mxf", "COPYING", "COMPLETED")

        with pytest.raises(FileCopyError, match="State transition"):
            await strategy.copy_file(str(source), str(dest), tf)


class TestCopyFileErrorPaths:

    async def test_source_size_timeout_raises(self, strategy, tmp_path):
        tf = _make_tracked_file()
        strategy._get_file_size = AsyncMock(side_effect=FileCopyTimeoutError("timeout"))

        with pytest.raises(FileCopyTimeoutError):
            await strategy.copy_file("/fake/source", "/fake/dest", tf)

    async def test_source_access_error_raises(self, strategy, tmp_path):
        tf = _make_tracked_file()
        strategy._get_file_size = AsyncMock(side_effect=FileCopyIOError("access denied"))

        with pytest.raises(FileCopyIOError):
            await strategy.copy_file("/fake/source", "/fake/dest", tf)

    async def test_makedirs_fails_raises_io_error(self, strategy, tmp_path):
        source = tmp_path / "test.mxf"
        source.write_bytes(b"x" * 2000)
        tf = _make_tracked_file(file_path=str(source), file_size=2000)

        with patch("aiofiles.os.makedirs", new_callable=AsyncMock, side_effect=PermissionError("no access")):
            with pytest.raises(FileCopyIOError, match="Directory creation failed"):
                await strategy.copy_file(str(source), "/invalid\x00/dest/test.mxf", tf)

    async def test_copy_growing_file_fails_raises(self, strategy, tmp_path):
        source = tmp_path / "test.mxf"
        source.write_bytes(b"x" * 2000)
        dest = tmp_path / "dest" / "test.mxf"
        tf = _make_tracked_file(file_path=str(source), file_size=2000)

        strategy._copy_growing_file = AsyncMock(side_effect=FileCopyError("IO failed"))

        with pytest.raises(FileCopyError):
            await strategy.copy_file(str(source), str(dest), tf)

    async def test_network_error_propagated(self, strategy, tmp_path):
        source = tmp_path / "test.mxf"
        source.write_bytes(b"x" * 2000)
        dest = tmp_path / "dest" / "test.mxf"
        tf = _make_tracked_file(file_path=str(source), file_size=2000)

        strategy._copy_growing_file = AsyncMock(side_effect=NetworkError("connection lost"))

        with pytest.raises(NetworkError):
            await strategy.copy_file(str(source), str(dest), tf)

    async def test_file_not_found_propagated(self, strategy, tmp_path):
        source = tmp_path / "test.mxf"
        source.write_bytes(b"x" * 2000)
        dest = tmp_path / "dest" / "test.mxf"
        tf = _make_tracked_file(file_path=str(source), file_size=2000)

        strategy._copy_growing_file = AsyncMock(side_effect=FileNotFoundError("gone"))

        with pytest.raises(FileNotFoundError):
            await strategy.copy_file(str(source), str(dest), tf)


class TestCopyFileConflictResolution:
    """Test destination conflict detection using real filesystem."""

    async def test_existing_dest_gets_copy1_suffix(self, strategy, tmp_path):
        source = tmp_path / "source" / "test.mxf"
        source.parent.mkdir()
        source.write_bytes(b"x" * 2000)

        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        # Pre-create the destination to trigger conflict
        (dest_dir / "test.mxf").write_bytes(b"existing")
        dest = dest_dir / "test.mxf"

        tf = _make_tracked_file(file_path=str(source), file_size=2000)

        # Capture which dest_path was passed to _copy_growing_file
        captured_dest = []
        async def capture_copy(src, dst, tracked, nd):
            captured_dest.append(dst)
            return True

        strategy._copy_growing_file = capture_copy

        await strategy.copy_file(str(source), str(dest), tf)

        assert len(captured_dest) == 1
        assert "_copy1" in captured_dest[0]


# ---------------------------------------------------------------------------
# TestCopyGrowingFile — real tmp_path, mocked io_loop
# ---------------------------------------------------------------------------

class TestCopyGrowingFile:

    async def test_static_file_disables_safety_margin(
        self, strategy, settings, tmp_path, io_loop
    ):
        source = tmp_path / "test.mxf"
        source.write_bytes(b"x" * 4096)
        dest = tmp_path / "output.mxf"
        tf = _make_tracked_file(file_size=4096)

        io_loop.copy_chunk_range.return_value = (4096, 100, 0.0, AsyncMock())
        network_detector = MagicMock(spec=NetworkErrorDetector)

        result = await strategy._copy_growing_file(
            str(source), str(dest), tf, network_detector
        )

        assert result is True
        # Verify io_loop was called — pause_ms should be 0 for static file
        call_args = io_loop.copy_chunk_range.call_args
        pause_arg = call_args[0][8]  # 9th positional arg is pause_ms (shifted by dest_path)
        assert pause_arg == 0

    async def test_growing_file_uses_safety_margin(
        self, strategy, settings, tmp_path, io_loop
    ):
        source = tmp_path / "test.mxf"
        source.write_bytes(b"x" * 4096)
        dest = tmp_path / "output.mxf"
        tf = _make_tracked_file(status=FileStatus.GROWING, growth_rate_mbps=5.0, file_size=4096)

        # Simulate: first call returns partial, second call completes
        # The loop will see file not growing (same size over cycles) and switch to full speed
        io_loop.copy_chunk_range.return_value = (4096, 100, 0.0, AsyncMock())
        # Mock _get_file_size to return constant size (triggers growth stopped)
        strategy._get_file_size = AsyncMock(return_value=4096)

        network_detector = MagicMock(spec=NetworkErrorDetector)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await strategy._copy_growing_file(
                str(source), str(dest), tf, network_detector
            )

        assert result is True

    async def test_creates_dest_file(self, strategy, tmp_path, io_loop):
        source = tmp_path / "test.mxf"
        source.write_bytes(b"x" * 4096)
        dest = tmp_path / "output.mxf"
        tf = _make_tracked_file(file_size=4096)

        io_loop.copy_chunk_range.return_value = (4096, 100, 0.0, AsyncMock())
        network_detector = MagicMock(spec=NetworkErrorDetector)

        await strategy._copy_growing_file(str(source), str(dest), tf, network_detector)

        # Dest file should have been created (empty since io_loop is mocked)
        assert dest.exists()

    async def test_network_error_in_loop_propagates(self, strategy, tmp_path, io_loop):
        source = tmp_path / "test.mxf"
        source.write_bytes(b"x" * 4096)
        dest = tmp_path / "output.mxf"
        tf = _make_tracked_file(file_size=4096)

        io_loop.copy_chunk_range.side_effect = NetworkError("SMB disconnected")
        network_detector = MagicMock(spec=NetworkErrorDetector)
        network_detector.check_write_error.side_effect = NetworkError("SMB disconnected")

        with pytest.raises(NetworkError):
            await strategy._copy_growing_file(str(source), str(dest), tf, network_detector)


# ---------------------------------------------------------------------------
# TestGrowingCopyLoop — growth detection logic
# ---------------------------------------------------------------------------

class TestGrowingCopyLoop:

    def _make_network_detector(self):
        nd = MagicMock(spec=NetworkErrorDetector)
        return nd

    async def test_static_file_copies_in_one_iteration(self, strategy, io_loop):
        """Static file: file_finished_growing=True from start, no safety margin."""
        tf = _make_tracked_file(file_size=10000)
        dst = AsyncMock()

        strategy._get_file_size = AsyncMock(return_value=10000)
        io_loop.copy_chunk_range.return_value = (10000, 100, 0.0, AsyncMock())

        result, _ = await strategy._growing_copy_loop(
            source_path="/fake/test.mxf",
            dst=dst,
            dest_path="/fake/output.mxf",
            initial_tracked_file=tf,
            bytes_copied=0,
            last_file_size=0,
            no_growth_cycles=5,  # >= max_no_growth_cycles → file_finished_growing
            max_no_growth_cycles=2,
            safety_margin_bytes=0,
            chunk_size=4096,
            poll_interval=0,
            pause_ms=0,
            network_detector=self._make_network_detector(),
        )

        assert result == 10000
        assert io_loop.copy_chunk_range.call_count == 1

    async def test_growing_file_detects_growth_stop(self, strategy, io_loop):
        """Simulate a file that grows once, then stops. Loop should detect and finish."""
        tf = _make_tracked_file(status=FileStatus.GROWING, growth_rate_mbps=5.0, file_size=20000)
        dst = AsyncMock()

        # Simulate file growing: 10000 → 15000 → 15000 → 15000 (stops) + re-read
        size_sequence = [10000, 15000, 15000, 15000, 15000]
        strategy._get_file_size = AsyncMock(side_effect=size_sequence)

        # io_loop returns the safe_copy_to each time
        call_count = [0]
        async def mock_copy_chunk_range(src, d, dp, start, end, cs, tracked, fs, pause, nd, status, pp, pt):
            call_count[0] += 1
            return (end, int((end / 15000) * 100), 0.0, d)

        io_loop.copy_chunk_range = mock_copy_chunk_range

        result, _ = await strategy._growing_copy_loop(
            source_path="/fake/test.mxf",
            dst=dst,
            dest_path="/fake/output.mxf",
            initial_tracked_file=tf,
            bytes_copied=0,
            last_file_size=0,
            no_growth_cycles=0,
            max_no_growth_cycles=2,  # 2 cycles without growth → finished
            safety_margin_bytes=1000,
            chunk_size=4096,
            poll_interval=0,
            pause_ms=0,
            network_detector=self._make_network_detector(),
        )

        assert result == 15000  # Copied all bytes
        assert call_count[0] >= 2  # At least 2 copy passes

    async def test_growing_file_uses_safety_margin(self, strategy, io_loop):
        """When file is still growing, safe_copy_to should be file_size - safety_margin."""
        tf = _make_tracked_file(status=FileStatus.GROWING, growth_rate_mbps=5.0, file_size=50000)
        dst = AsyncMock()

        safety_margin = 5000

        # File keeps growing: 50000 → 50000 (no growth → cycle 1) → 50000 (cycle 2 → finished) + re-read
        strategy._get_file_size = AsyncMock(side_effect=[50000, 50000, 50000, 50000])

        captured_ranges = []
        async def mock_copy_chunk_range(src, d, dp, start, end, cs, tracked, fs, pause, nd, status, pp, pt):
            captured_ranges.append((start, end))
            return (end, 100, 0.0, d)

        io_loop.copy_chunk_range = mock_copy_chunk_range

        await strategy._growing_copy_loop(
            source_path="/fake/test.mxf",
            dst=dst,
            dest_path="/fake/output.mxf",
            initial_tracked_file=tf,
            bytes_copied=0,
            last_file_size=0,
            no_growth_cycles=0,
            max_no_growth_cycles=2,
            safety_margin_bytes=safety_margin,
            chunk_size=4096,
            poll_interval=0,
            pause_ms=0,
            network_detector=self._make_network_detector(),
        )

        # First copy should use safety margin: safe_copy_to = 50000 - 5000 = 45000
        first_start, first_end = captured_ranges[0]
        assert first_end == 50000 - safety_margin

    async def test_throttle_when_close_to_write_head(self, strategy, io_loop):
        """When distance from write head < 2x safety margin, use_pause should be True."""
        tf = _make_tracked_file(status=FileStatus.GROWING, growth_rate_mbps=5.0, file_size=50000)
        dst = AsyncMock()

        safety_margin = 20000  # Large margin

        # File: 50000, safety=20000, safe_copy_to=30000
        # Start bytes_copied at 25000 so distance = 50000 - 25000 = 25000
        # buffer_zone = 2*20000 = 40000. 25000 < 40000 → throttled
        # Then growth stops → full speed (+ re-read after exit)
        strategy._get_file_size = AsyncMock(side_effect=[50000, 50000, 50000, 50000])

        captured_pause = []
        async def mock_copy_chunk_range(src, d, dp, start, end, cs, tracked, fs, pause, nd, status, pp, pt):
            captured_pause.append(pause)
            return (end, 100, 0.0, d)

        io_loop.copy_chunk_range = mock_copy_chunk_range

        await strategy._growing_copy_loop(
            source_path="/fake/test.mxf",
            dst=dst,
            dest_path="/fake/output.mxf",
            initial_tracked_file=tf,
            bytes_copied=25000,  # Start close to write head
            last_file_size=0,
            no_growth_cycles=0,
            max_no_growth_cycles=2,
            safety_margin_bytes=safety_margin,
            chunk_size=4096,
            poll_interval=0,
            pause_ms=50,  # Non-zero pause to detect throttle
            network_detector=self._make_network_detector(),
        )

        # First call should have pause (throttled), last should be 0 (full speed after growth stop)
        assert captured_pause[0] == 50  # throttled
        assert captured_pause[-1] == 0  # full speed after growth stopped

    async def test_full_speed_when_far_from_write_head(self, strategy, io_loop):
        """When distance > 2x safety margin, no throttle even while growing."""
        tf = _make_tracked_file(status=FileStatus.GROWING, growth_rate_mbps=5.0, file_size=100000)
        dst = AsyncMock()

        safety_margin = 1000  # Small margin

        # File: 100000, bytes_copied starts at 0
        # safe_copy_to = 99000
        # distance_from_write_head = 100000 - 0 = 100000
        # buffer_zone = 2000. 100000 > 2000 → full speed
        # Then file stops growing after 2 cycles (+ re-read after exit)
        strategy._get_file_size = AsyncMock(side_effect=[100000, 100000, 100000, 100000])

        captured_pause = []
        async def mock_copy_chunk_range(src, d, dp, start, end, cs, tracked, fs, pause, nd, status, pp, pt):
            captured_pause.append(pause)
            return (end, 100, 0.0, d)

        io_loop.copy_chunk_range = mock_copy_chunk_range

        await strategy._growing_copy_loop(
            source_path="/fake/test.mxf",
            dst=dst,
            dest_path="/fake/output.mxf",
            initial_tracked_file=tf,
            bytes_copied=0,
            last_file_size=0,
            no_growth_cycles=0,
            max_no_growth_cycles=2,
            safety_margin_bytes=safety_margin,
            chunk_size=4096,
            poll_interval=0,
            pause_ms=50,
            network_detector=self._make_network_detector(),
        )

        # First call should be full speed (far from write head)
        assert captured_pause[0] == 0

    async def test_status_matches_phase(self, strategy, io_loop):
        """GROWING_COPY status while growing, COPYING after growth stops."""
        tf = _make_tracked_file(status=FileStatus.GROWING, growth_rate_mbps=5.0, file_size=50000)
        dst = AsyncMock()

        # File grows, then stops (+ re-read after exit)
        strategy._get_file_size = AsyncMock(side_effect=[50000, 50000, 50000, 50000])

        captured_status = []
        async def mock_copy_chunk_range(src, d, dp, start, end, cs, tracked, fs, pause, nd, status, pp, pt):
            captured_status.append(status)
            return (end, 100, 0.0, d)

        io_loop.copy_chunk_range = mock_copy_chunk_range

        await strategy._growing_copy_loop(
            source_path="/fake/test.mxf",
            dst=dst,
            dest_path="/fake/output.mxf",
            initial_tracked_file=tf,
            bytes_copied=0,
            last_file_size=0,
            no_growth_cycles=0,
            max_no_growth_cycles=2,
            safety_margin_bytes=5000,
            chunk_size=4096,
            poll_interval=0,
            pause_ms=0,
            network_detector=self._make_network_detector(),
        )

        # First call is GROWING_COPY (still growing), last is COPYING (growth stopped)
        assert captured_status[0] == FileStatus.GROWING_COPY
        assert captured_status[-1] == FileStatus.COPYING

    async def test_file_size_error_propagates(self, strategy, io_loop):
        """If _get_file_size fails in the loop, error propagates."""
        tf = _make_tracked_file(file_size=10000)
        dst = AsyncMock()

        strategy._get_file_size = AsyncMock(side_effect=FileCopyIOError("disk gone"))

        with pytest.raises(FileCopyIOError):
            await strategy._growing_copy_loop(
                source_path="/fake/test.mxf",
                dst=dst,
                dest_path="/fake/output.mxf",
                initial_tracked_file=tf,
                bytes_copied=0,
                last_file_size=0,
                no_growth_cycles=5,
                max_no_growth_cycles=2,
                safety_margin_bytes=0,
                chunk_size=4096,
                poll_interval=0,
                pause_ms=0,
                network_detector=self._make_network_detector(),
            )


# ---------------------------------------------------------------------------
# TestCopyFileWaitForMinSize — growing file waits for minimum size
# ---------------------------------------------------------------------------

class TestCopyFileWaitForMinSize:

    async def test_growing_file_waits_then_copies(self, strategy, settings, tmp_path, state_machine, verification_service):
        """Growing file below min size waits, then proceeds when large enough."""
        source = tmp_path / "test.mxf"
        # Start small (100KB < 1MB min)
        source.write_bytes(b"x" * 100_000)
        dest = tmp_path / "dest" / "test.mxf"

        tf = _make_tracked_file(
            file_path=str(source),
            status=FileStatus.GROWING,
            file_size=100_000,
            growth_rate_mbps=5.0,
        )

        # _get_file_size: first returns 100KB (small), then 2MB (big enough)
        min_size = settings.growing_file_min_size_mb * 1024 * 1024  # 1MB
        strategy._get_file_size = AsyncMock(side_effect=[100_000, 2_000_000])
        strategy._copy_growing_file = AsyncMock(return_value=True)
        verification_service.verify_integrity.return_value = (True, 2_000_000, 2_000_000)
        verification_service.delete_source_file.return_value = (True, None)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await strategy.copy_file(str(source), str(dest), tf)

        assert result is True
        # _get_file_size called twice: once initial, once in while loop
        assert strategy._get_file_size.call_count == 2

    async def test_static_file_skips_min_size_wait(self, strategy, tmp_path, state_machine, verification_service):
        """Static file (not growing) skips the min-size wait entirely."""
        source = tmp_path / "test.mxf"
        source.write_bytes(b"x" * 500)  # small file
        dest = tmp_path / "dest" / "test.mxf"

        tf = _make_tracked_file(
            file_path=str(source),
            status=FileStatus.READY,
            file_size=500,
            growth_rate_mbps=0.0,
        )

        strategy._copy_growing_file = AsyncMock(return_value=True)
        verification_service.verify_integrity.return_value = (True, 500, 500)
        verification_service.delete_source_file.return_value = (True, None)

        result = await strategy.copy_file(str(source), str(dest), tf)

        assert result is True
        # No asyncio.sleep should have been called for min-size wait


# ---------------------------------------------------------------------------
# TestEventPublishing
# ---------------------------------------------------------------------------

class TestEventPublishing:

    async def test_completed_event_published_with_correct_bytes(
        self, strategy, tmp_path, event_bus, verification_service
    ):
        source = tmp_path / "test.mxf"
        source.write_bytes(b"x" * 5000)
        dest = tmp_path / "dest" / "test.mxf"
        tf = _make_tracked_file(file_path=str(source), file_size=5000)

        strategy._copy_growing_file = AsyncMock(return_value=True)
        verification_service.verify_integrity.return_value = (True, 5000, 5000)
        verification_service.delete_source_file.return_value = (True, None)

        await strategy.copy_file(str(source), str(dest), tf)

        event_bus.publish.assert_called_once()
        event = event_bus.publish.call_args[0][0]
        assert isinstance(event, FileCopyCompletedEvent)
        assert event.bytes_copied == 5000
        assert event.source_size == 5000
        assert event.dest_size == 5000

    async def test_no_event_published_when_delete_fails(
        self, strategy, tmp_path, event_bus, verification_service
    ):
        source = tmp_path / "test.mxf"
        source.write_bytes(b"x" * 5000)
        dest = tmp_path / "dest" / "test.mxf"
        tf = _make_tracked_file(file_path=str(source), file_size=5000)

        strategy._copy_growing_file = AsyncMock(return_value=True)
        verification_service.verify_integrity.return_value = (True, 5000, 5000)
        verification_service.delete_source_file.return_value = (False, "still recording")

        await strategy.copy_file(str(source), str(dest), tf)

        # When delete fails → COMPLETED_DELETE_FAILED, no event published
        event_bus.publish.assert_not_called()


# ---------------------------------------------------------------------------
# TestSourceDeletionSafety — CRITICAL: source must NEVER be deleted for partial copies
# Incident 2026-03-27: source was deleted when dest < source (growing file)
# ---------------------------------------------------------------------------

class TestSourceDeletionSafety:
    """Gate 2: delete_source_file must only be called when dest == source size."""

    async def test_source_grew_after_copy_raises_integrity_error(
        self, strategy, tmp_path, verification_service
    ):
        """If source grew during copy (dest < source), raise integrity error — never delete."""
        source = tmp_path / "source" / "test.mxf"
        source.parent.mkdir()
        source.write_bytes(b"x" * 10000)
        dest = tmp_path / "dest" / "test.mxf"
        tf = _make_tracked_file(file_path=str(source), file_size=10000)

        strategy._copy_growing_file = AsyncMock(return_value=True)
        # Simulate: source grew to 10000 but only 7000 was copied
        verification_service.verify_integrity.return_value = (False, 10000, 7000)

        with pytest.raises(FileCopyIntegrityError):
            await strategy.copy_file(str(source), str(dest), tf)

        # Source must NOT have been deleted
        verification_service.delete_source_file.assert_not_awaited()

    async def test_exact_match_allows_deletion(
        self, strategy, tmp_path, state_machine, verification_service, event_bus
    ):
        """When source and dest sizes match exactly, deletion is allowed."""
        source = tmp_path / "source" / "test.mxf"
        source.parent.mkdir()
        source.write_bytes(b"x" * 7000)
        dest = tmp_path / "dest" / "test.mxf"
        tf = _make_tracked_file(file_path=str(source), file_size=7000)

        strategy._copy_growing_file = AsyncMock(return_value=True)
        verification_service.verify_integrity.return_value = (True, 7000, 7000)
        verification_service.delete_source_file.return_value = (True, None)

        result = await strategy.copy_file(str(source), str(dest), tf)

        assert result is True
        verification_service.delete_source_file.assert_awaited_once()
        call_kwargs = state_machine.transition.call_args.kwargs
        assert call_kwargs["new_status"] == FileStatus.COMPLETED

    async def test_delete_never_called_on_verification_failure(
        self, strategy, tmp_path, verification_service
    ):
        """Verification failure must prevent any source deletion attempt."""
        source = tmp_path / "source" / "test.mxf"
        source.parent.mkdir()
        source.write_bytes(b"x" * 5000)
        dest = tmp_path / "dest" / "test.mxf"
        tf = _make_tracked_file(file_path=str(source), file_size=5000)

        strategy._copy_growing_file = AsyncMock(return_value=True)
        verification_service.verify_integrity.return_value = (False, 5000, 3000)

        with pytest.raises(FileCopyIntegrityError):
            await strategy.copy_file(str(source), str(dest), tf)

        verification_service.delete_source_file.assert_not_awaited()


# ---------------------------------------------------------------------------
# TestCopyLoopPostExitRecheck — loop must re-verify size before exiting
# Incident 2026-03-27: loop exited with stale current_file_size while source grew
# ---------------------------------------------------------------------------

class TestCopyLoopPostExitRecheck:

    def _make_network_detector(self):
        return MagicMock(spec=NetworkErrorDetector)

    async def test_loop_continues_when_file_grew_after_growth_stopped(self, strategy, io_loop):
        """After declaring GROWTH STOPPED, if source grew during catch-up, loop must continue."""
        tf = _make_tracked_file(status=FileStatus.GROWING, growth_rate_mbps=5.0, file_size=20000)
        dst = AsyncMock()

        # Sequence: 10000 → 10000 → 10000 (growth stops) → re-read: 12000 (grew!) → 12000 (copy) → re-read: 12000 (done)
        strategy._get_file_size = AsyncMock(side_effect=[10000, 10000, 10000, 12000, 12000, 12000])

        async def mock_copy_chunk_range(src, d, dp, start, end, cs, tracked, fs, pause, nd, status, pp, pt):
            return (end, 100, 0.0, d)

        io_loop.copy_chunk_range = mock_copy_chunk_range

        result, _ = await strategy._growing_copy_loop(
            source_path="/fake/test.mxf",
            dst=dst,
            dest_path="/fake/output.mxf",
            initial_tracked_file=tf,
            bytes_copied=0,
            last_file_size=0,
            no_growth_cycles=0,
            max_no_growth_cycles=2,
            safety_margin_bytes=1000,
            chunk_size=4096,
            poll_interval=0,
            pause_ms=0,
            network_detector=self._make_network_detector(),
        )

        # Must have copied ALL 12000 bytes, not just the 10000 from first detection
        assert result == 12000

    async def test_loop_exits_when_final_recheck_confirms_no_growth(self, strategy, io_loop):
        """After growth stopped and catch-up, re-read confirms same size → safe to exit."""
        tf = _make_tracked_file(status=FileStatus.GROWING, growth_rate_mbps=5.0, file_size=10000)
        dst = AsyncMock()

        # Sequence: 10000 → 10000 → 10000 (stops) → re-read 10000 (same → exit)
        strategy._get_file_size = AsyncMock(side_effect=[10000, 10000, 10000, 10000])

        async def mock_copy_chunk_range(src, d, dp, start, end, cs, tracked, fs, pause, nd, status, pp, pt):
            return (end, 100, 0.0, d)

        io_loop.copy_chunk_range = mock_copy_chunk_range

        result, _ = await strategy._growing_copy_loop(
            source_path="/fake/test.mxf",
            dst=dst,
            dest_path="/fake/output.mxf",
            initial_tracked_file=tf,
            bytes_copied=0,
            last_file_size=0,
            no_growth_cycles=0,
            max_no_growth_cycles=2,
            safety_margin_bytes=1000,
            chunk_size=4096,
            poll_interval=0,
            pause_ms=0,
            network_detector=self._make_network_detector(),
        )

        assert result == 10000
