"""
Tests for CopyIoLoop - the byte-for-byte I/O copy engine.

Uses real temp files for source, an in-memory mock for dst, and mocked
state_machine / event_bus to avoid external dependencies.
"""
import asyncio
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

        bytes_copied, last_pct, last_time, _ = await loop.copy_chunk_range(
            source_path=str(source),
            dst=dst,
            dest_path=str(tmp_path / "dest.bin"),
            start_bytes=0,
            end_bytes=4096,
            chunk_size=1024,
            tracked_file=tracked_file,
            current_file_size=4096,
            pause_ms=0,
            network_detector=network_detector,
            status=FileStatus.COPYING,
            last_progress_percent=0,
            last_progress_mono=0.0,
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

        bytes_copied, _, _, _ = await loop.copy_chunk_range(
            source_path=str(source),
            dst=dst,
            dest_path=str(tmp_path / "dest.bin"),
            start_bytes=1000,
            end_bytes=2000,
            chunk_size=512,
            tracked_file=tracked_file,
            current_file_size=3000,
            pause_ms=0,
            network_detector=network_detector,
            status=FileStatus.COPYING,
            last_progress_percent=0,
            last_progress_mono=0.0,
        )

        assert bytes_copied == 2000
        total_written = sum(len(c) for c in written_chunks)
        assert total_written == 1000  # only 1000 bytes (range 1000-2000)

    async def test_write_error_triggers_network_check(self, loop, tracked_file, tmp_path):
        """A write error that looks like network failure should raise NetworkError."""
        source = tmp_path / "source.bin"
        source.write_bytes(b"X" * 512)
        dest = tmp_path / "dest.bin"
        dest.write_bytes(b"\x00" * 512)

        # Ensure all reopened dst handles also fail, even after a retry reopen
        failing_dst = AsyncMock()
        failing_dst.write = AsyncMock(side_effect=OSError("connection refused"))
        failing_dst.seek = AsyncMock()
        failing_dst.close = AsyncMock()

        # Mock src to return valid data so read never fails
        src_mock = AsyncMock()
        src_mock.read = AsyncMock(return_value=b"X" * 256)
        src_mock.seek = AsyncMock()
        src_mock.close = AsyncMock()

        async def patched_open(path, mode="rb"):
            if "+" in mode:  # r+b destination
                return failing_dst
            return src_mock  # rb source

        dst = AsyncMock()
        dst.write = AsyncMock(side_effect=OSError("connection refused"))
        dst.seek = AsyncMock()
        dst.close = AsyncMock()

        detector = NetworkErrorDetector()

        with patch("app.domains.file_processing.copy.copy_io_loop.aiofiles.open", side_effect=patched_open):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(NetworkError):
                    await loop.copy_chunk_range(
                        source_path=str(source),
                        dst=dst,
                        dest_path=str(dest),
                        start_bytes=0,
                        end_bytes=512,
                        chunk_size=256,
                        tracked_file=tracked_file,
                        current_file_size=512,
                        pause_ms=0,
                        network_detector=detector,
                        status=FileStatus.COPYING,
                        last_progress_percent=0,
                        last_progress_mono=0.0,
                    )

    async def test_nonexistent_source_raises(self, loop, tracked_file, network_detector):
        """Opening a nonexistent source file should raise."""
        dst = AsyncMock()

        with pytest.raises(FileNotFoundError):
            await loop.copy_chunk_range(
                source_path="/nonexistent/path.mxf",
                dst=dst,
                dest_path="/fake/dest.bin",
                start_bytes=0,
                end_bytes=100,
                chunk_size=50,
                tracked_file=tracked_file,
                current_file_size=100,
                pause_ms=0,
                network_detector=network_detector,
                status=FileStatus.COPYING,
                last_progress_percent=0,
                last_progress_mono=0.0,
            )

    async def test_zero_range_copies_nothing(self, loop, tracked_file, network_detector, tmp_path):
        """If start_bytes == end_bytes, no data should be copied."""
        source = tmp_path / "source.bin"
        source.write_bytes(b"data")

        dst = AsyncMock()

        bytes_copied, _, _, _ = await loop.copy_chunk_range(
            source_path=str(source),
            dst=dst,
            dest_path="/fake/dest.bin",
            start_bytes=0,
            end_bytes=0,
            chunk_size=1024,
            tracked_file=tracked_file,
            current_file_size=4,
            pause_ms=0,
            network_detector=network_detector,
            status=FileStatus.COPYING,
            last_progress_percent=0,
            last_progress_mono=0.0,
        )

        assert bytes_copied == 0
        dst.write.assert_not_called()


# ── _initial_seek ───────────────────────────────────────────────────────────

class TestInitialSeek:

    @pytest.fixture
    def loop(self):
        settings = MagicMock()
        settings.file_operation_timeout_seconds = 1.0
        return CopyIoLoop(settings, AsyncMock(), AsyncMock())

    async def test_successful_seek(self, loop):
        src = AsyncMock()
        detector = MagicMock()

        await loop._initial_seek(src, "/test.mxf", 1024, detector)

        src.seek.assert_awaited_once_with(1024)

    async def test_timeout_raises_file_copy_timeout(self, loop):
        src = AsyncMock()
        src.seek = AsyncMock(side_effect=asyncio.TimeoutError())
        detector = MagicMock()

        with pytest.raises(FileCopyTimeoutError, match="seek timeout"):
            await loop._initial_seek(src, "/test.mxf", 0, detector)

    async def test_os_error_triggers_network_check(self, loop):
        src = AsyncMock()
        err = OSError("I/O error")
        src.seek = AsyncMock(side_effect=err)
        detector = MagicMock()
        detector.check_write_error = MagicMock(side_effect=NetworkError("net"))

        with pytest.raises(NetworkError):
            await loop._initial_seek(src, "/test.mxf", 0, detector)

        detector.check_write_error.assert_called_once_with(err, "file seek operation")

    async def test_generic_error_triggers_network_check_then_reraises(self, loop):
        """Non-network OSError: check_write_error doesn't raise, original re-raised."""
        src = AsyncMock()
        err = OSError("disk full")
        src.seek = AsyncMock(side_effect=err)
        detector = MagicMock()
        detector.check_write_error = MagicMock()  # doesn't raise

        with pytest.raises(OSError, match="disk full"):
            await loop._initial_seek(src, "/test.mxf", 0, detector)


# ── _write_chunk_with_retry ─────────────────────────────────────────────────

class TestWriteChunkWithRetry:

    @pytest.fixture
    def loop(self):
        settings = MagicMock()
        settings.file_operation_timeout_seconds = 1.0
        return CopyIoLoop(settings, AsyncMock(), AsyncMock())

    async def test_successful_read_write(self, loop):
        src = AsyncMock()
        src.read = AsyncMock(return_value=b"ABCD")
        dst = AsyncMock()
        detector = MagicMock()

        chunk, _, _ = await loop._write_chunk_with_retry(
            src, dst, "/test.mxf", "/test_dst.mxf", 0, 4, 3, detector
        )

        assert chunk == b"ABCD"
        dst.write.assert_awaited_once_with(b"ABCD")

    async def test_eof_returns_empty_bytes(self, loop):
        src = AsyncMock()
        src.read = AsyncMock(return_value=b"")
        dst = AsyncMock()
        detector = MagicMock()

        chunk, _, _ = await loop._write_chunk_with_retry(
            src, dst, "/test.mxf", "/test_dst.mxf", 100, 50, 3, detector
        )

        assert chunk == b""
        dst.write.assert_not_awaited()

    async def test_retry_on_timeout_then_succeeds(self, loop):
        src = AsyncMock()
        src.read = AsyncMock(side_effect=asyncio.TimeoutError())
        src.close = AsyncMock()
        dst = AsyncMock()
        dst.close = AsyncMock()
        detector = MagicMock()

        new_src = AsyncMock()
        new_src.read = AsyncMock(return_value=b"OK")
        new_src.seek = AsyncMock()
        new_dst = AsyncMock()
        new_dst.seek = AsyncMock()

        async def mock_open(path, mode="rb"):
            if "+" in mode:
                return new_dst
            return new_src

        with patch("app.domains.file_processing.copy.copy_io_loop.aiofiles.open", side_effect=mock_open):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                chunk, final_src, final_dst = await loop._write_chunk_with_retry(
                    src, dst, "/test.mxf", "/test_dst.mxf", 0, 2, 3, detector
                )

        assert chunk == b"OK"
        src.close.assert_awaited_once()
        dst.close.assert_awaited_once()
        new_src.seek.assert_awaited_once_with(0)
        new_dst.seek.assert_awaited_once_with(0)

    async def test_max_retries_timeout_raises_copy_timeout(self, loop):
        src = AsyncMock()
        src.read = AsyncMock(side_effect=asyncio.TimeoutError())
        dst = AsyncMock()
        detector = MagicMock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(FileCopyTimeoutError):
                await loop._write_chunk_with_retry(
                    src, dst, "/test.mxf", "/test_dst.mxf", 0, 10, 1, detector  # max_retries=1
                )

    async def test_max_retries_os_error_triggers_network_check(self, loop):
        src = AsyncMock()
        err = OSError("connection refused")
        src.read = AsyncMock(side_effect=err)
        dst = AsyncMock()
        detector = MagicMock()
        detector.check_write_error = MagicMock(side_effect=NetworkError("net"))

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(NetworkError):
                await loop._write_chunk_with_retry(
                    src, dst, "/test.mxf", "/test_dst.mxf", 0, 10, 1, detector
                )

    async def test_generic_exception_triggers_network_check(self, loop):
        src = AsyncMock()
        err = ValueError("unexpected")
        src.read = AsyncMock(side_effect=err)
        dst = AsyncMock()
        detector = MagicMock()
        detector.check_write_error = MagicMock()  # doesn't raise

        with pytest.raises(ValueError, match="unexpected"):
            await loop._write_chunk_with_retry(
                src, dst, "/test.mxf", "/test_dst.mxf", 0, 10, 3, detector
            )

    async def test_exponential_backoff_timing(self, loop):
        src = AsyncMock()
        src.read = AsyncMock(side_effect=asyncio.TimeoutError())
        src.close = AsyncMock()
        dst = AsyncMock()
        dst.close = AsyncMock()
        detector = MagicMock()
        sleep_calls = []

        # Retry 1: new_src1 still times out; retry 2: new_src2 succeeds
        new_src1 = AsyncMock()
        new_src1.read = AsyncMock(side_effect=asyncio.TimeoutError())
        new_src1.seek = AsyncMock()
        new_src1.close = AsyncMock()

        new_src2 = AsyncMock()
        new_src2.read = AsyncMock(return_value=b"OK")
        new_src2.seek = AsyncMock()

        new_dst1 = AsyncMock()
        new_dst1.seek = AsyncMock()
        new_dst1.close = AsyncMock()

        new_dst2 = AsyncMock()
        new_dst2.seek = AsyncMock()

        open_returns = iter([new_src1, new_dst1, new_src2, new_dst2])

        async def mock_open(path, mode="rb"):
            return next(open_returns)

        async def mock_sleep(seconds):
            sleep_calls.append(seconds)

        with patch("app.domains.file_processing.copy.copy_io_loop.aiofiles.open", side_effect=mock_open):
            with patch("asyncio.sleep", side_effect=mock_sleep):
                chunk, _, _ = await loop._write_chunk_with_retry(
                    src, dst, "/test.mxf", "/test_dst.mxf", 0, 2, 5, detector
                )

        assert chunk == b"OK"
        assert sleep_calls == [2, 4]  # 2^1, 2^2


# ── _report_progress ────────────────────────────────────────────────────────

class TestReportProgress:

    @pytest.fixture
    def state_machine(self):
        return AsyncMock()

    @pytest.fixture
    def event_bus(self):
        return AsyncMock()

    @pytest.fixture
    def loop(self, state_machine, event_bus):
        settings = MagicMock()
        return CopyIoLoop(settings, state_machine, event_bus)

    @pytest.fixture
    def tracked_file(self):
        return TrackedFile(file_path="/src/test.mxf", file_size=1000)

    async def test_publishes_event_and_transitions(self, loop, state_machine, event_bus, tracked_file):
        await loop._report_progress(
            tracked_file, FileStatus.COPYING,
            bytes_copied=500, current_file_size=1000,
            copy_start_mono=0.0, copy_start_bytes=0,
        )

        state_machine.transition.assert_awaited_once()
        call_kw = state_machine.transition.call_args[1]
        assert call_kw["file_id"] == tracked_file.id
        assert call_kw["new_status"] == FileStatus.COPYING
        assert 49.0 <= call_kw["copy_progress"] <= 51.0

    async def test_zero_file_size_no_division_error(self, loop, state_machine, tracked_file):
        await loop._report_progress(
            tracked_file, FileStatus.COPYING,
            bytes_copied=0, current_file_size=0,
            copy_start_mono=0.0, copy_start_bytes=0,
        )

        call_kw = state_machine.transition.call_args[1]
        assert call_kw["copy_progress"] == 0

    async def test_transition_invalid_error_logged(self, loop, state_machine, tracked_file):
        from app.core.exceptions import InvalidTransitionError
        state_machine.transition.side_effect = InvalidTransitionError("f", "A", "B")

        # Should not raise
        await loop._report_progress(
            tracked_file, FileStatus.COPYING,
            bytes_copied=100, current_file_size=1000,
            copy_start_mono=0.0, copy_start_bytes=0,
        )

    async def test_transition_unexpected_error_logged(self, loop, state_machine, tracked_file):
        state_machine.transition.side_effect = RuntimeError("boom")

        # Should not raise
        await loop._report_progress(
            tracked_file, FileStatus.COPYING,
            bytes_copied=100, current_file_size=1000,
            copy_start_mono=0.0, copy_start_bytes=0,
        )

    async def test_no_event_bus(self, state_machine, tracked_file):
        settings = MagicMock()
        loop = CopyIoLoop(settings, state_machine, None)

        # Should not raise even without event_bus
        await loop._report_progress(
            tracked_file, FileStatus.COPYING,
            bytes_copied=500, current_file_size=1000,
            copy_start_mono=0.0, copy_start_bytes=0,
        )

        state_machine.transition.assert_awaited_once()

    async def test_event_publish_error_logged(self, state_machine, tracked_file):
        settings = MagicMock()
        event_bus = MagicMock()  # Not AsyncMock — create_task will fail
        event_bus.publish = MagicMock(side_effect=RuntimeError("pub fail"))
        loop = CopyIoLoop(settings, state_machine, event_bus)

        # Should not raise — event error is caught
        await loop._report_progress(
            tracked_file, FileStatus.COPYING,
            bytes_copied=500, current_file_size=1000,
            copy_start_mono=0.0, copy_start_bytes=0,
        )


# ── Chunk retry integration tests ──────────────────────────────────────────

class TestChunkRetryIntegration:
    """Integration tests for retry behavior through copy_chunk_range."""

    @pytest.fixture
    def settings(self):
        s = Settings()
        s.file_operation_timeout_seconds = 5.0
        return s

    @pytest.fixture
    def loop(self, settings):
        return CopyIoLoop(settings, AsyncMock(spec=FileStateMachine), AsyncMock(spec=DomainEventBus))

    @pytest.fixture
    def tracked_file(self):
        return TrackedFile(file_path="/src/test.mxf", file_size=1024)

    @pytest.fixture
    def network_detector(self):
        return NetworkErrorDetector()

    async def test_chunk_retry_on_transient_timeout(self, loop, tracked_file, network_detector, tmp_path):
        """A single timeout should be retried, not cause immediate failure."""
        source = tmp_path / "source.bin"
        data = b"A" * 1024
        source.write_bytes(data)
        dest = tmp_path / "dest.bin"
        dest.write_bytes(b"")  # pre-create for r+b open on retry

        dst = AsyncMock()
        call_count = [0]

        async def write_with_first_timeout(chunk):
            call_count[0] += 1
            if call_count[0] == 1:
                raise asyncio.TimeoutError("transient timeout")
            # On retry dst is a real handle; this mock is not called again

        dst.write = AsyncMock(side_effect=write_with_first_timeout)
        dst.seek = AsyncMock()
        dst.close = AsyncMock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            bytes_copied, _, _, _ = await loop.copy_chunk_range(
                source_path=str(source),
                dst=dst,
                dest_path=str(dest),
                start_bytes=0,
                end_bytes=1024,
                chunk_size=1024,
                tracked_file=tracked_file,
                current_file_size=1024,
                pause_ms=0,
                network_detector=network_detector,
                status=FileStatus.COPYING,
                last_progress_percent=0,
                last_progress_mono=0.0,
            )

        assert bytes_copied == 1024  # succeeded on retry via fresh file handle

    async def test_chunk_retry_exhausted_raises(self, loop, tracked_file, network_detector, tmp_path):
        """If all retries are exhausted, the error should propagate."""
        source = tmp_path / "source.bin"
        source.write_bytes(b"X" * 512)
        dest = tmp_path / "dest.bin"
        dest.write_bytes(b"")

        # Ensure all reopened dst handles keep timing out
        always_timing_out_dst = AsyncMock()
        always_timing_out_dst.write = AsyncMock(side_effect=asyncio.TimeoutError("persistent timeout"))
        always_timing_out_dst.seek = AsyncMock()
        always_timing_out_dst.close = AsyncMock()

        # Mock src to return valid data so read never fails
        src_mock = AsyncMock()
        src_mock.read = AsyncMock(return_value=b"X" * 256)
        src_mock.seek = AsyncMock()
        src_mock.close = AsyncMock()

        async def patched_open(path, mode="rb"):
            if "+" in mode:
                return always_timing_out_dst
            return src_mock

        dst = AsyncMock()
        dst.write = AsyncMock(side_effect=asyncio.TimeoutError("persistent timeout"))
        dst.seek = AsyncMock()
        dst.close = AsyncMock()

        with patch("app.domains.file_processing.copy.copy_io_loop.aiofiles.open", side_effect=patched_open):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(FileCopyTimeoutError):
                    await loop.copy_chunk_range(
                        source_path=str(source),
                        dst=dst,
                        dest_path=str(dest),
                        start_bytes=0,
                        end_bytes=512,
                        chunk_size=256,
                        tracked_file=tracked_file,
                        current_file_size=512,
                        pause_ms=0,
                        network_detector=network_detector,
                        status=FileStatus.COPYING,
                        last_progress_percent=0,
                        last_progress_mono=0.0,
                    )

    async def test_chunk_retry_on_transient_oserror(self, loop, tracked_file, network_detector, tmp_path):
        """A transient OSError should be retried before failing."""
        source = tmp_path / "source.bin"
        source.write_bytes(b"A" * 512)
        dest = tmp_path / "dest.bin"
        dest.write_bytes(b"")  # pre-create for r+b open on retry

        dst = AsyncMock()
        call_count = [0]

        async def write_with_transient_error(chunk):
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSError("temporary I/O glitch")
            # On retry dst is a real handle; this mock is not called again

        dst.write = AsyncMock(side_effect=write_with_transient_error)
        dst.seek = AsyncMock()
        dst.close = AsyncMock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            bytes_copied, _, _, _ = await loop.copy_chunk_range(
                source_path=str(source),
                dst=dst,
                dest_path=str(dest),
                start_bytes=0,
                end_bytes=512,
                chunk_size=512,
                tracked_file=tracked_file,
                current_file_size=512,
                pause_ms=0,
                network_detector=network_detector,
                status=FileStatus.COPYING,
                last_progress_percent=0,
                last_progress_mono=0.0,
            )

        assert bytes_copied == 512
