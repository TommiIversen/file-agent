"""
Tests for JobErrorClassifier - determines the correct FileStatus for copy errors.
"""
import errno
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock

import pytest

from app.models import FileStatus, StorageStatus
from app.domains.file_processing.consumer.job_error_classifier import JobErrorClassifier
from app.domains.file_processing.copy.network_error_detector import NetworkError
from app.domains.file_processing.copy.exceptions import (
    FileCopyError,
    FileCopyTimeoutError,
    FileCopyIOError,
    FileCopyIntegrityError,
)


@pytest.fixture
def storage_monitor():
    """Mock StorageMonitorService with healthy destination."""
    monitor = MagicMock()
    dest_info = MagicMock()
    dest_info.status = StorageStatus.OK
    monitor.get_destination_info.return_value = dest_info
    return monitor


@pytest.fixture
def classifier(storage_monitor):
    return JobErrorClassifier(storage_monitor)


# ── Typed exception classification ──────────────────────────────────────────

class TestTypedExceptions:

    def test_network_error_returns_failed(self, classifier):
        err = NetworkError("Network failure detected: connection refused")
        status, reason = classifier.classify_copy_error(err, "/src/video.mxf")
        assert status == FileStatus.FAILED
        assert "Network failure" in reason

    def test_file_not_found_returns_removed(self, classifier):
        err = FileNotFoundError("Source file gone")
        status, reason = classifier.classify_copy_error(err, "/src/video.mxf")
        assert status == FileStatus.REMOVED
        assert "FileNotFoundError" in reason

    def test_timeout_error_returns_waiting_for_network(self, classifier):
        err = FileCopyTimeoutError("Read timeout")
        status, reason = classifier.classify_copy_error(err, "/src/video.mxf")
        assert status == FileStatus.WAITING_FOR_NETWORK
        assert "timed out" in reason

    def test_io_error_returns_failed(self, classifier):
        err = FileCopyIOError("I/O breakdown")
        status, reason = classifier.classify_copy_error(err, "/src/video.mxf")
        assert status == FileStatus.FAILED
        assert "I/O error" in reason

    def test_integrity_error_returns_failed(self, classifier):
        err = FileCopyIntegrityError("Checksum mismatch")
        status, reason = classifier.classify_copy_error(err, "/src/video.mxf")
        assert status == FileStatus.FAILED
        assert "integrity" in reason

    def test_generic_copy_error_returns_failed(self, classifier):
        err = FileCopyError("Something broke")
        status, reason = classifier.classify_copy_error(err, "/src/video.mxf")
        assert status == FileStatus.FAILED
        assert "General copy error" in reason


# ── Destination unavailability ──────────────────────────────────────────────

class TestDestinationUnavailable:

    def test_error_status_returns_failed(self, storage_monitor):
        dest_info = MagicMock()
        dest_info.status = StorageStatus.ERROR
        storage_monitor.get_destination_info.return_value = dest_info
        classifier = JobErrorClassifier(storage_monitor)

        err = Exception("some random error")
        status, reason = classifier.classify_copy_error(err, "/src/video.mxf")
        assert status == FileStatus.FAILED
        assert "Destination unavailable" in reason

    def test_critical_status_returns_failed(self, storage_monitor):
        dest_info = MagicMock()
        dest_info.status = StorageStatus.CRITICAL
        storage_monitor.get_destination_info.return_value = dest_info
        classifier = JobErrorClassifier(storage_monitor)

        err = Exception("something went wrong")
        status, reason = classifier.classify_copy_error(err, "/src/video.mxf")
        assert status == FileStatus.FAILED
        assert "Destination unavailable" in reason


# ── String-based network error detection ────────────────────────────────────

class TestStringBasedNetworkErrors:

    @pytest.mark.parametrize("error_msg,expected_indicator", [
        ("input/output error on /mnt/nas", "input/output error"),
        ("errno 5 I/O failure", "errno 5"),
        ("Connection refused by host", "connection refused"),
        ("Network is unreachable", "network is unreachable"),
        ("Broken pipe during write", "broken pipe"),
        ("WinError 53: network path was not found", "network path was not found"),
        ("WinError 67: the network name cannot be found", "the network name cannot be found"),
        ("Access is denied on share", "access is denied"),
    ])
    def test_network_string_errors_return_failed(self, classifier, error_msg, expected_indicator):
        status, reason = classifier.classify_copy_error(Exception(error_msg), "/src/video.mxf")
        assert status == FileStatus.FAILED
        assert "Network error" in reason or "network" in reason.lower()


# ── Errno-based network error detection ─────────────────────────────────────

class TestErrnoBasedNetworkErrors:

    @pytest.mark.parametrize("errno_code", [
        errno.EIO,
        errno.ECONNREFUSED,
        errno.ETIMEDOUT,
        errno.ENETUNREACH,
        errno.EHOSTUNREACH,
        errno.EPIPE,
    ])
    def test_network_errno_returns_failed(self, classifier, errno_code):
        err = OSError(errno_code, "OS error")
        err.errno = errno_code
        # The error string might not match network strings, so we need a
        # string that doesn't match source errors or network strings
        # to ensure we're testing errno detection specifically
        status, reason = classifier.classify_copy_error(err, "/src/video.mxf")
        assert status == FileStatus.FAILED


# ── Source file errors ──────────────────────────────────────────────────────

class TestSourceFileErrors:

    def test_source_file_gone_returns_removed(self, classifier, tmp_path):
        nonexistent = str(tmp_path / "gone.mxf")
        err = Exception("No such file or directory: gone.mxf")
        status, reason = classifier.classify_copy_error(err, nonexistent)
        assert status == FileStatus.REMOVED

    def test_source_still_exists_returns_failed(self, classifier, tmp_path):
        existing = tmp_path / "exists.mxf"
        existing.write_bytes(b"data")
        err = Exception("source file read error")
        status, reason = classifier.classify_copy_error(err, str(existing))
        assert status == FileStatus.FAILED


# ── Default / unknown errors ────────────────────────────────────────────────

class TestDefaultErrors:

    def test_unknown_error_defaults_to_failed(self, classifier, tmp_path):
        existing = tmp_path / "exists.mxf"
        existing.write_bytes(b"data")
        err = Exception("totally unknown error xyz")
        status, reason = classifier.classify_copy_error(err, str(existing))
        assert status == FileStatus.FAILED
        assert "Unknown error" in reason


# ── Internal helpers ────────────────────────────────────────────────────────

class TestHelpers:

    def test_is_network_error_true(self, classifier):
        assert classifier._is_network_error(Exception("ok"), "connection refused") is True

    def test_is_network_error_false(self, classifier):
        err = Exception("nothing wrong")
        assert classifier._is_network_error(err, "disk quota exceeded") is False

    def test_get_network_error_reason_string_match(self, classifier):
        reason = classifier._get_network_error_reason(Exception("test"), "broken pipe here")
        assert "broken pipe" in reason

    def test_get_network_error_reason_errno_match(self, classifier):
        err = OSError(errno.EIO, "I/O")
        err.errno = errno.EIO
        reason = classifier._get_network_error_reason(err, "something else")
        assert "errno" in reason.lower()

    def test_is_source_error_string_match(self, classifier):
        assert classifier._is_source_error("no such file or directory: test.mxf", "/src/test.mxf") is True


# ── Timeout errors should enable network recovery ──────────────────────────
# Incident 2026-03-27: FileCopyTimeoutError was classified as FAILED, preventing
# automatic retry on network recovery. It should be WAITING_FOR_NETWORK.

class TestTimeoutNetworkRecovery:

    def test_timeout_error_classified_as_waiting_for_network(self, classifier):
        """FileCopyTimeoutError during copy should allow network recovery retry."""
        err = FileCopyTimeoutError("Read timeout after 30s")
        status, reason = classifier.classify_copy_error(err, "/src/video.mxf")
        assert status == FileStatus.WAITING_FOR_NETWORK

    def test_io_error_stays_failed(self, classifier):
        """Non-timeout I/O errors should still be FAILED (no change)."""
        err = FileCopyIOError("Disk read error")
        status, reason = classifier.classify_copy_error(err, "/src/video.mxf")
        assert status == FileStatus.FAILED

    def test_is_source_error_file_not_found(self, classifier, tmp_path):
        nonexistent = str(tmp_path / "ghost.mxf")
        assert classifier._is_source_error("some error", nonexistent) is True

    def test_get_source_error_reason_string_match(self, classifier):
        reason = classifier._get_source_error_reason("file not found at path", "/src/a.mxf")
        assert "file not found" in reason

    def test_destination_status_string(self, classifier):
        status = classifier._get_destination_status()
        assert status.lower() == "ok"

    def test_destination_status_no_info(self, storage_monitor):
        storage_monitor.get_destination_info.return_value = None
        classifier = JobErrorClassifier(storage_monitor)
        assert classifier._get_destination_status() == "unknown"
