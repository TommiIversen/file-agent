"""
Job Error Classifier - determines if copy errors should pause, fail, or remove file.
"""

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

    def __init__(self, storage_monitor: StorageInfoProvider):
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
            - WAITING_FOR_NETWORK: Timeout errors
        """
        # 1. Handle typed exceptions first (fail-fast from copier)
        if isinstance(error, NetworkError):
            return FileStatus.FAILED, f"Network failure detected: {str(error)}"
        elif isinstance(error, FileNotFoundError):
            return FileStatus.REMOVED, "Source file no longer exists (FileNotFoundError)"
        elif isinstance(error, FileCopyTimeoutError):
            return FileStatus.WAITING_FOR_NETWORK, f"File operation timed out (awaiting network recovery): {str(error)}"
        elif isinstance(error, FileCopyIOError):
            return FileStatus.FAILED, f"File I/O error: {str(error)}"
        elif isinstance(error, FileCopyIntegrityError):
            return FileStatus.FAILED, f"File integrity check failed: {str(error)}"
        elif isinstance(error, FileCopyError):
            return FileStatus.FAILED, f"General copy error: {str(error)}"

        # 2. Check destination status
        if self._is_destination_unavailable():
            return (
                FileStatus.FAILED,
                f"Destination unavailable (status: {self._get_destination_status()})",
            )

        error_str = str(error).lower()

        # 3. Reuse regex + errno logic from NetworkErrorDetector (single source of truth)
        if self._is_network_error(error, error_str):
            return FileStatus.FAILED, f"Network error identified: {error_str}"

        # 4. Check for source file errors
        if self._is_source_error(error_str):
            if not self._source_file_exists(file_path):
                return FileStatus.REMOVED, "Source file disappeared during operation"
            return FileStatus.FAILED, f"Source error detected: {self._get_source_error_indicator(error_str)}"

        # 5. Default fallback
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
