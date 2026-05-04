"""
Job Error Classifier - determines if copy errors should pause, fail, or remove file.
"""

import errno
import logging
from pathlib import Path
from typing import Tuple

from app.models import StorageStatus, FileStatus, StorageInfoProvider
from app.domains.file_processing.copy.network_error_detector import NetworkErrorDetector, NetworkError
from app.domains.file_processing.copy.exceptions import FileCopyError, FileCopyTimeoutError, FileCopyIOError, FileCopyIntegrityError


class JobErrorClassifier:
    """Classifies copy errors to determine pause vs fail strategy."""

    # Source file error indicators (specific to consumer/job handling)
    SOURCE_ERROR_STRINGS = {
        "no such file or directory",
        "errno 2",
        "file not found",
        "source file",
        "input file",
    }

    # Disk-space errno codes
    SPACE_ERRNO_CODES = {errno.ENOSPC}  # 28 on Linux/macOS/Windows

    # Disk-space error string patterns
    SPACE_ERROR_STRINGS = [
        "no space left",
        "not enough space",
        "disk full",
        "errno 28",
        "enospc",
    ]

    def __init__(self, storage_monitor: StorageInfoProvider):
        self.storage_monitor = storage_monitor

    def classify_copy_error(
        self, error: Exception, file_path: str
    ) -> Tuple[FileStatus, str]:
        """
        Classify copy error to determine appropriate FileStatus and reason.

        Returns:
            Tuple of (FileStatus, reason) where:
            - WAITING_FOR_SPACE: Disk full during copy (retryable)
            - WAITING_FOR_NETWORK: Network timeout or network error during copy
            - REMOVED: Source file disappeared
            - FAILED: Unrecoverable errors
        """
        # 1. Handle typed exceptions first (fail-fast from copier)
        if isinstance(error, NetworkError):
            return FileStatus.WAITING_FOR_NETWORK, f"Network connection lost during copy: {str(error)}"
        elif isinstance(error, FileNotFoundError):
            return FileStatus.REMOVED, "Source file no longer exists (FileNotFoundError)"
        elif isinstance(error, FileCopyTimeoutError):
            return FileStatus.WAITING_FOR_NETWORK, f"Connection timed out — waiting for recovery: {str(error)}"
        elif isinstance(error, FileCopyIOError):
            # Check if this is a disk-space IO error
            if self._is_space_error(error):
                return FileStatus.WAITING_FOR_SPACE, "Low disk space on destination"
            return FileStatus.FAILED, f"File I/O error: {str(error)}"
        elif isinstance(error, FileCopyIntegrityError):
            return FileStatus.FAILED, f"File integrity check failed: {str(error)}"
        elif isinstance(error, FileCopyError):
            return FileStatus.FAILED, f"General copy error: {str(error)}"

        # 2. Check destination status
        if self._is_destination_unavailable():
            dest_status = self._get_destination_status()
            if self._is_destination_space_issue():
                return FileStatus.WAITING_FOR_SPACE, f"Low disk space on destination (status: {dest_status})"
            return (
                FileStatus.WAITING_FOR_NETWORK,
                f"Destination not accessible (status: {dest_status})",
            )

        error_str = str(error).lower()

        # 3. Check for disk-space errors in generic exceptions
        if self._is_space_error(error):
            return FileStatus.WAITING_FOR_SPACE, "Low disk space on destination"

        # 4. Reuse regex + errno logic from NetworkErrorDetector (single source of truth)
        if self._is_network_error(error, error_str):
            return FileStatus.WAITING_FOR_NETWORK, f"Network error during copy: {error_str}"

        # 5. Check for source file errors
        if self._is_source_error(error_str):
            if not self._source_file_exists(file_path):
                return FileStatus.REMOVED, "Source file disappeared during operation"
            return FileStatus.FAILED, f"Source error detected: {self._get_source_error_indicator(error_str)}"

        # 6. Default fallback
        logging.warning(
            f"Unknown error type for {Path(file_path).name}: {error_str} → defaulting to FAILED"
        )
        return FileStatus.FAILED, f"Unknown error (immediate failure): {str(error)}"

    def _is_destination_unavailable(self) -> bool:
        """Check if destination is currently unavailable."""
        destination_info = self.storage_monitor.get_destination_info()
        return bool(destination_info and destination_info.status in [
            StorageStatus.ERROR,
            StorageStatus.CRITICAL,
        ])

    def _is_destination_space_issue(self) -> bool:
        """Check if destination unavailability is due to disk space (CRITICAL + accessible)."""
        destination_info = self.storage_monitor.get_destination_info()
        return bool(
            destination_info
            and destination_info.status == StorageStatus.CRITICAL
            and destination_info.is_accessible
        )

    def _get_destination_status(self) -> str:
        """Get current destination status."""
        destination_info = self.storage_monitor.get_destination_info()
        return destination_info.status.value if destination_info else "unknown"

    def _is_network_error(self, error: Exception, error_str: str) -> bool:
        """Check if error indicates network/destination issues using NetworkErrorDetector's logic."""
        if NetworkErrorDetector._NETWORK_ERROR_PATTERN.search(error_str):
            return True
        if hasattr(error, "errno") and error.errno in NetworkErrorDetector.NETWORK_ERRNO_CODES:
            return True
        return False

    def _is_space_error(self, error: Exception) -> bool:
        """Check if error indicates disk-space exhaustion."""
        if hasattr(error, "errno") and error.errno in self.SPACE_ERRNO_CODES:
            return True
        error_str = str(error).lower()
        return any(pattern in error_str for pattern in self.SPACE_ERROR_STRINGS)

    def _is_source_error(self, error_str: str) -> bool:
        """Check if error string indicates source file issues."""
        return any(indicator in error_str for indicator in self.SOURCE_ERROR_STRINGS)

    def _get_source_error_indicator(self, error_str: str) -> str:
        """Get the specific reason string for source error classification."""
        for indicator in self.SOURCE_ERROR_STRINGS:
            if indicator in error_str:
                return indicator
        return "Unknown source error"

    def _source_file_exists(self, file_path: str) -> bool:
        """Safely check if source file exists."""
        try:
            return Path(file_path).exists()
        except Exception as e:
            logging.debug(f"Could not verify file existence for {file_path}: {e}")
            return False
