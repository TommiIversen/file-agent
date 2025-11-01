"""
Job Error Classifier - determines if copy errors should pause, fail, or remove file.
"""

import errno
import logging
import os
from pathlib import Path
from typing import Tuple

from app.models import StorageStatus, FileStatus
from app.domains.file_processing.copy.network_error_detector import NetworkError
from app.domains.file_processing.copy.exceptions import FileCopyError, FileCopyTimeoutError, FileCopyIOError, FileCopyIntegrityError
from app.services.storage_monitor.storage_monitor import StorageMonitorService


class JobErrorClassifier:
    """Classifies copy errors to determine pause vs fail strategy."""

    # Network/destination error indicators
    NETWORK_ERROR_STRINGS = {
        "input/output error",
        "errno 5",
        "connection refused",
        "network is unreachable",
        "no route to host",
        "connection timed out",
        "broken pipe",
        "errno 32",
        "errno 110",
        "errno 111",
        "smb error",
        "cifs error",
        "mount_smbfs",
        "network mount",
        "permission denied",
        "invalid argument",
        "errno 22",
        "network path was not found",
        "winerror 53",
        "the network name cannot be found",
        "winerror 67",
        "the network location cannot be reached",
        "winerror 1231",
        "access is denied",
        "errno 13",
    }

    # Source file error indicators
    SOURCE_ERROR_STRINGS = {
        "no such file or directory",
        "errno 2",
        "file not found",
        "source file",
        "input file",
    }

    # Network-related errno codes (including Windows-specific)
    NETWORK_ERRNO_CODES = {
        errno.EIO,
        errno.ECONNREFUSED,
        errno.ETIMEDOUT,
        errno.ENETUNREACH,
        errno.EHOSTUNREACH,
        errno.EPIPE,
        errno.EACCES,
        errno.ENOTCONN,
        errno.ECONNRESET,
        errno.EINVAL,  # Can be network-related on Windows when destination unavailable
        errno.ENOENT,  # Network path not found
        errno.EACCES,  # Access denied (can be network mount issues)
        22,
        53,
        67,
        1231,
        13,  # Windows-specific network error codes including errno 22
    }

    def __init__(self, storage_monitor: StorageMonitorService):
        self.storage_monitor = storage_monitor

    def classify_copy_error(
        self, error: Exception, file_path: str
    ) -> Tuple[FileStatus, str]:
        """
        Classify copy error to determine appropriate FileStatus and reason.

        Returns:
            Tuple of (FileStatus, reason) where:
            - FAILED: Network/destination issues (fail-and-rediscover strategy)
            - REMOVED: Source file disappeared
            - FAILED: Technical copy errors
        """
        # Handle NetworkError from fail-fast detection immediately
        if isinstance(error, NetworkError):
            return FileStatus.FAILED, f"Network failure detected: {str(error)}"
        elif isinstance(error, FileNotFoundError):
            # This is already handled by _is_source_error, but good to be explicit
            return FileStatus.REMOVED, "Source file no longer exists (FileNotFoundError)"
        elif isinstance(error, FileCopyTimeoutError):
            return FileStatus.FAILED, f"File operation timed out: {str(error)}"
        elif isinstance(error, FileCopyIOError):
            return FileStatus.FAILED, f"File I/O error: {str(error)}"
        elif isinstance(error, FileCopyIntegrityError):
            return FileStatus.FAILED, f"File integrity check failed: {str(error)}"
        elif isinstance(error, FileCopyError):
            return FileStatus.FAILED, f"General copy error: {str(error)}"

        # Check destination status first
        if self._is_destination_unavailable():
            return (
                FileStatus.FAILED,
                f"Destination unavailable (status: {self._get_destination_status()})",
            )

        error_str = str(error).lower()

        # Check for network errors (now fail immediately in fail-and-rediscover)
        if self._is_network_error(error, error_str):
            return FileStatus.FAILED, self._get_network_error_reason(error, error_str)

        # Check for source errors (should remove if file disappeared, otherwise fail)
        if self._is_source_error(error_str, file_path):
            # If source file no longer exists, mark as REMOVED instead of FAILED
            try:
                if not Path(file_path).exists():
                    return FileStatus.REMOVED, "Source file no longer exists"
            except Exception:
                pass

            # Other source errors should fail
            return FileStatus.FAILED, self._get_source_error_reason(
                error_str, file_path
            )

        # Default to fail for unknown errors (fail-and-rediscover strategy)
        logging.warning(
            f"Unknown error type for {Path(file_path).name}: {error_str} → defaulting to FAILED"
        )
        return FileStatus.FAILED, f"Unknown error (immediate failure): {str(error)}"

    def _is_destination_unavailable(self) -> bool:
        """Check if destination is currently unavailable."""
        destination_info = self.storage_monitor.get_destination_info()
        return destination_info and destination_info.status in [
            StorageStatus.ERROR,
            StorageStatus.CRITICAL,
        ]

    def _get_destination_status(self) -> str:
        """Get current destination status."""
        destination_info = self.storage_monitor.get_destination_info()
        return destination_info.status.value if destination_info else "unknown"

    def _is_network_error(self, error: Exception, error_str: str) -> bool:
        """Check if error indicates network/destination issues."""
        # Check string indicators
        if any(indicator in error_str for indicator in self.NETWORK_ERROR_STRINGS):
            return True

        # Check errno codes
        if hasattr(error, "errno") and error.errno in self.NETWORK_ERRNO_CODES:
            return True

        return False

    def _get_network_error_reason(self, error: Exception, error_str: str) -> str:
        """Get reason for network error classification."""
        # Check string match first
        for indicator in self.NETWORK_ERROR_STRINGS:
            if indicator in error_str:
                return f"Network error detected: {indicator}"

        # Check errno
        if hasattr(error, "errno") and error.errno in self.NETWORK_ERRNO_CODES:
            return f"Network errno {error.errno}: {os.strerror(error.errno)}"

        return "Network error detected"

    def _is_source_error(self, error_str: str, file_path: str) -> bool:
        """Check if error indicates source file issues."""
        # Check string indicators
        if any(indicator in error_str for indicator in self.SOURCE_ERROR_STRINGS):
            return True

        # Check if source file still exists
        try:
            return not Path(file_path).exists()
        except Exception:
            return False

    def _get_source_error_reason(self, error_str: str, file_path: str) -> str:
        """Get reason for source error classification."""
        # Check string match first
        for indicator in self.SOURCE_ERROR_STRINGS:
            if indicator in error_str:
                return f"Source error: {indicator}"

        # Check file existence
        try:
            if not Path(file_path).exists():
                return "Source file no longer exists"
        except Exception:
            pass

        return "Source file error"
