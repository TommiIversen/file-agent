"""
Tests for CopyIoLoop - the byte-for-byte I/O copy engine.

Uses real temp files for source, an in-memory mock for dst, and mocked
state_machine / event_bus to avoid external dependencies.
"""
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.core.events.event_bus import DomainEventBus
from app.core.file_state_machine import FileStateMachine
from app.models import TrackedFile, FileStatus
from app.domains.file_processing.copy.copy_io_loop import CopyIoLoop, calculate_transfer_rate
from app.domains.file_processing.copy.network_error_detector import NetworkErrorDetector, NetworkError
from app.domains.file_processing.copy.exceptions import FileCopyTimeoutError


# ── calculate_transfer_rate ─────────────────────────────────────────────────

class TestCalculateTransferRate:

    def test_normal_rate(self):
        assert calculate_transfer_rate(10_000_000, 2.0) == 5_000_000.0

    def test_zero_elapsed(self):
        assert calculate_transfer_rate(10_000_000, 0.0) == 0.0

    def test_negative_elapsed(self):
        assert calculate_transfer_rate(10_000_000, -1.0) == 0.0

    def test_zero_bytes(self):
        assert calculate_transfer_rate(0, 5.0) == 0.0


# ── CopyIoLoop with real temp files ────────────────────────────────────────

class TestCopyIoLoop:

    @pytest.fixture
    def settings(self):
        s = Settings()
        s.file_operation_timeout_seconds = 5.0
        return s

    @pytest.fixture
    def state_machine(self):
        sm = AsyncMock(spec=FileStateMachine)
        return sm

    @pytest.fixture
    def event_bus(self):
        eb = AsyncMock(spec=DomainEventBus)
        return eb

    @pytest.fixture
    def loop(self, settings, state_machine, event_bus):
        return CopyIoLoop(settings, state_machine, event_bus)

    @pytest.fixture
    def tracked_file(self):
        return TrackedFile(file_path="/src/test.mxf", file_size=1024)

    @pytest.fixture
    def network_detector(self):
        return NetworkErrorDetector()

    async def test_copies_all_bytes(self, loop, tracked_file, network_detector, tmp_path):
        """Full copy of a small file through the IO loop."""
        source = tmp_path / "source.bin"
        data = b"A" * 4096
        source.write_bytes(data)

        dst = AsyncMock()
        written_chunks = []
        dst.write = AsyncMock(side_effect=lambda chunk: written_chunks.append(chunk))

        bytes_copied, last_pct, last_time = await loop.copy_chunk_range(
            source_path=str(source),
            dst=dst,
            start_bytes=0,
            end_bytes=4096,
            chunk_size=1024,
            tracked_file=tracked_file,
            current_file_size=4096,
            pause_ms=0,
            network_detector=network_detector,
            status=FileStatus.COPYING,
            last_progress_percent=0,
            last_progress_update_time=datetime.now(),
        )

        assert bytes_copied == 4096
        total_written = sum(len(c) for c in written_chunks)
        assert total_written == 4096

    async def test_copies_partial_range(self, loop, tracked_file, network_detector, tmp_path):
        """Copy only a range within a larger file."""
        source = tmp_path / "source.bin"
        data = b"A" * 1000 + b"B" * 1000 + b"C" * 1000
        source.write_bytes(data)

        dst = AsyncMock()
        written_chunks = []
        dst.write = AsyncMock(side_effect=lambda chunk: written_chunks.append(chunk))

        bytes_copied, _, _ = await loop.copy_chunk_range(
            source_path=str(source),
            dst=dst,
            start_bytes=1000,
            end_bytes=2000,
            chunk_size=512,
            tracked_file=tracked_file,
            current_file_size=3000,
            pause_ms=0,
            network_detector=network_detector,
            status=FileStatus.COPYING,
            last_progress_percent=0,
            last_progress_update_time=datetime.now(),
        )

        assert bytes_copied == 2000
        total_written = sum(len(c) for c in written_chunks)
        assert total_written == 1000  # only 1000 bytes (range 1000-2000)

    async def test_write_error_triggers_network_check(self, loop, tracked_file, tmp_path):
        """A write error that looks like network failure should raise NetworkError."""
        source = tmp_path / "source.bin"
        source.write_bytes(b"X" * 512)

        dst = AsyncMock()
        dst.write = AsyncMock(side_effect=OSError("connection refused"))

        detector = NetworkErrorDetector()

        with pytest.raises(NetworkError):
            await loop.copy_chunk_range(
                source_path=str(source),
                dst=dst,
                start_bytes=0,
                end_bytes=512,
                chunk_size=256,
                tracked_file=tracked_file,
                current_file_size=512,
                pause_ms=0,
                network_detector=detector,
                status=FileStatus.COPYING,
                last_progress_percent=0,
                last_progress_update_time=datetime.now(),
            )

    async def test_nonexistent_source_raises(self, loop, tracked_file, network_detector):
        """Opening a nonexistent source file should raise."""
        dst = AsyncMock()

        with pytest.raises(FileNotFoundError):
            await loop.copy_chunk_range(
                source_path="/nonexistent/path.mxf",
                dst=dst,
                start_bytes=0,
                end_bytes=100,
                chunk_size=50,
                tracked_file=tracked_file,
                current_file_size=100,
                pause_ms=0,
                network_detector=network_detector,
                status=FileStatus.COPYING,
                last_progress_percent=0,
                last_progress_update_time=datetime.now(),
            )

    async def test_zero_range_copies_nothing(self, loop, tracked_file, network_detector, tmp_path):
        """If start_bytes == end_bytes, no data should be copied."""
        source = tmp_path / "source.bin"
        source.write_bytes(b"data")

        dst = AsyncMock()

        bytes_copied, _, _ = await loop.copy_chunk_range(
            source_path=str(source),
            dst=dst,
            start_bytes=0,
            end_bytes=0,
            chunk_size=1024,
            tracked_file=tracked_file,
            current_file_size=4,
            pause_ms=0,
            network_detector=network_detector,
            status=FileStatus.COPYING,
            last_progress_percent=0,
            last_progress_update_time=datetime.now(),
        )

        assert bytes_copied == 0
        dst.write.assert_not_called()
