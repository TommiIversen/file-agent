"""
Tests for NetworkErrorDetector - detects network errors during copy operations.
"""
import asyncio
import errno
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.file_processing.copy.network_error_detector import (
    NetworkErrorDetector,
    NetworkError,
)


# ── String-based detection ──────────────────────────────────────────────────

class TestNetworkErrorStringDetection:

    @pytest.mark.parametrize("error_msg", [
        "Input/Output error on /mnt/nas",
        "connection refused by remote host",
        "Network is unreachable",
        "No route to host 192.168.1.1",
        "Connection timed out",
        "Broken pipe during write",
        "SMB error: session setup failed",
        "CIFS error: reconnect needed",
        "Permission denied: /mnt/share",
        "WinError 53: network path was not found",
        "WinError 67: the network name cannot be found",
        "WinError 1231: the network location cannot be reached",
        "access is denied for destination",
        "errno 5: I/O error",
        "errno 32: broken pipe",
        "errno 110: connection timed out",
        "errno 111: connection refused",
        "errno 22: invalid argument",
        "errno 13: permission denied",
    ])
    def test_raises_network_error_for_known_strings(self, error_msg):
        detector = NetworkErrorDetector()
        with pytest.raises(NetworkError, match="Network error during"):
            detector.check_write_error(Exception(error_msg), "test write")

    @pytest.mark.parametrize("error_msg", [
        "disk quota exceeded",
        "out of memory",
        "division by zero",
        "unexpected token in JSON",
        "file is too large",
    ])
    def test_does_not_raise_for_non_network_strings(self, error_msg):
        detector = NetworkErrorDetector()
        # Should not raise - just returns
        detector.check_write_error(Exception(error_msg), "test write")


# ── Errno-based detection ───────────────────────────────────────────────────

class TestNetworkErrorErrnoDetection:

    @pytest.mark.parametrize("errno_code", [
        errno.EIO,
        errno.ECONNREFUSED,
        errno.ETIMEDOUT,
        errno.ENETUNREACH,
        errno.EHOSTUNREACH,
        errno.EPIPE,
        errno.EACCES,
        errno.ENOTCONN,
        errno.ECONNRESET,
        errno.EINVAL,
        errno.ENOENT,
    ])
    def test_raises_network_error_for_known_errnos(self, errno_code):
        detector = NetworkErrorDetector()
        err = OSError(errno_code, "OS error")
        err.errno = errno_code
        with pytest.raises(NetworkError):
            detector.check_write_error(err, "test op")

    def test_does_not_raise_for_unknown_errno(self):
        detector = NetworkErrorDetector()
        err = OSError(999, "Unknown OS error")
        err.errno = 999
        # No network indicator string, unknown errno -> should NOT raise
        detector.check_write_error(err, "test op")


# ── Event publishing ────────────────────────────────────────────────────────

class TestNetworkErrorEventPublishing:

    async def test_publishes_event_on_network_error(self):
        event_bus = MagicMock()
        event_bus.publish = AsyncMock()
        detector = NetworkErrorDetector(event_bus=event_bus, current_file_id="file-123")

        with pytest.raises(NetworkError):
            detector.check_write_error(Exception("connection refused"), "chunk write")

        # Give create_task a chance to schedule
        await asyncio.sleep(0)

        # Verify event was published
        assert event_bus.publish.called
        assert detector._current_file_id == "file-123"

    def test_no_event_without_bus(self):
        detector = NetworkErrorDetector()  # No event_bus
        with pytest.raises(NetworkError):
            detector.check_write_error(Exception("connection refused"), "chunk write")

    def test_no_event_without_file_id(self):
        event_bus = MagicMock()
        detector = NetworkErrorDetector(event_bus=event_bus)  # No file_id
        with pytest.raises(NetworkError):
            detector.check_write_error(Exception("broken pipe"), "chunk write")


# ── Internal helpers ────────────────────────────────────────────────────────

class TestNetworkErrorDetectorHelpers:

    def test_is_network_error_string_true(self):
        detector = NetworkErrorDetector()
        assert detector._is_network_error_string("input/output error") is True

    def test_is_network_error_string_false(self):
        detector = NetworkErrorDetector()
        assert detector._is_network_error_string("something else entirely") is False

    def test_is_network_errno_true(self):
        detector = NetworkErrorDetector()
        err = OSError(errno.EIO, "I/O error")
        err.errno = errno.EIO
        assert detector._is_network_errno(err) is True

    def test_is_network_errno_false_no_attr(self):
        detector = NetworkErrorDetector()
        err = ValueError("not an OS error")
        assert detector._is_network_errno(err) is False

    def test_is_network_errno_false_unknown_code(self):
        detector = NetworkErrorDetector()
        err = OSError(999, "custom")
        err.errno = 999
        assert detector._is_network_errno(err) is False
