"""
Storage Checker Utility for File Transfer Agent.

Clean, reusable utility for checking storage health of a single path.
No state, no dependencies - pure function-like behavior.
"""

import os
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Tuple
from uuid import uuid4

import aiofiles


from ..models import StorageInfo, StorageStatus


class StorageAccessError(Exception):
    """Raised when storage access operations fail"""

    pass


class StorageChecker:
    """
    Pure utility class for checking storage health of a single path.

    Features:
    - Stateless design - hver check er uafhængig
    - Disk space monitoring
    - Mount/accessibility checks
    - Write access verification via test files
    - Configurable thresholds per check
    - Cross-platform compatibility

    Responsibility:
    Check ONE path and return StorageInfo. Intet state, ingen side effects.
    """

    def __init__(self, test_file_prefix: str = ".storage_test_"):
        """
        Initialize StorageChecker.

        Args:
            test_file_prefix: Prefix for test files during write checks
        """
        self._test_file_prefix = test_file_prefix

    async def check_path(
        self, path: str, warning_threshold_gb: float, critical_threshold_gb: float
    ) -> StorageInfo:
        """
        Check storage health for a single path.

        Args:
            path: Path to check (source or destination)
            warning_threshold_gb: Warning threshold in GB
            critical_threshold_gb: Critical threshold in GB

        Returns:
            StorageInfo with complete health metrics

        Raises:
            StorageAccessError: For unrecoverable access issues
        """
        logging.debug(f"Checking storage path: {path}")

        # Initialize defaults
        is_accessible = False
        has_write_access = False
        free_gb = 0.0
        total_gb = 0.0
        used_gb = 0.0
        error_message = None

        try:
            # Step 1: Check basic accessibility
            is_accessible = await self._check_accessibility(path)

            if is_accessible:
                # Step 2: Get disk usage metrics
                free_gb, total_gb, used_gb = await self._get_disk_usage(path)

                # Step 3: Verify write access
                has_write_access = await self._check_write_access(path)
            else:
                error_message = f"Path {path} is not accessible"

        except Exception as e:
            error_message = f"Storage check error: {str(e)}"
            logging.error(f"Storage check failed for {path}: {e}")

        # Evaluate overall status
        status = self._evaluate_status(
            free_gb,
            warning_threshold_gb,
            critical_threshold_gb,
            is_accessible,
            has_write_access,
        )

        return StorageInfo(
            path=path,
            is_accessible=is_accessible,
            has_write_access=has_write_access,
            free_space_gb=free_gb,
            total_space_gb=total_gb,
            used_space_gb=used_gb,
            status=status,
            warning_threshold_gb=warning_threshold_gb,
            critical_threshold_gb=critical_threshold_gb,
            last_checked=datetime.now(),
            error_message=error_message,
        )

    async def _check_accessibility(self, path: str) -> bool:
        """
        Check if path exists and is accessible.

        Args:
            path: Path to check

        Returns:
            True if path exists and is a directory
        """
        try:
            path_obj = Path(path)
            return path_obj.exists() and path_obj.is_dir()
        except Exception as e:
            logging.debug(f"Accessibility check failed for {path}: {e}")
            return False

    async def _get_disk_usage(self, path: str) -> Tuple[float, float, float]:
        """
        Get disk usage statistics for path.

        Args:
            path: Path to check disk usage for

        Returns:
            Tuple of (free_gb, total_gb, used_gb)

        Raises:
            StorageAccessError: If disk usage cannot be determined
        """
        try:
            # Cross-platform disk usage check
            total_bytes, used_bytes, free_bytes = shutil.disk_usage(path)

            # Convert to GB for easier handling
            gb_divisor = 1024**3
            total_gb = total_bytes / gb_divisor
            used_gb = used_bytes / gb_divisor
            free_gb = free_bytes / gb_divisor

            logging.debug(
                f"Disk usage for {path}: {free_gb:.1f}GB free of {total_gb:.1f}GB total"
            )

            return free_gb, total_gb, used_gb

        except Exception as e:
            logging.error(f"Cannot get disk usage for {path}: {e}")
            raise StorageAccessError(f"Disk usage check failed: {e}")

    async def _check_write_access(self, path: str) -> bool:
        """
        Verify write access by creating and cleaning up a test file.

        Args:
            path: Directory to test write access in

        Returns:
            True if write access is available
        """
        test_file_path = None

        try:
            # Create test file
            test_file_path = await self._create_test_file(path)

            # Clean up test file
            await self._cleanup_test_file(test_file_path)

            logging.debug(f"Write access verified for {path}")
            return True

        except Exception as e:
            logging.debug(f"Write access check failed for {path}: {e}")

            # Ensure cleanup even on failure
            if test_file_path:
                await self._cleanup_test_file(test_file_path)

            return False

    async def _create_test_file(self, directory: str) -> str:
        """
        Create temporary test file for write verification.

        Args:
            directory: Directory to create test file in

        Returns:
            Full path to created test file

        Raises:
            StorageAccessError: If test file cannot be created
        """
        # Generate unique test filename
        test_filename = f"{self._test_file_prefix}{uuid4().hex}.tmp"
        test_file_path = os.path.join(directory, test_filename)

        try:
            # Create and write test content
            async with aiofiles.open(test_file_path, "w") as f:
                await f.write("storage_write_test")

            logging.debug(f"Test file created: {test_file_path}")
            return test_file_path

        except Exception as e:
            raise StorageAccessError(f"Cannot create test file in {directory}: {e}")

    async def _cleanup_test_file(self, test_file_path: str) -> None:
        """
        Safely remove test file.

        Args:
            test_file_path: Path to test file to remove
        """
        try:
            if os.path.exists(test_file_path):
                os.remove(test_file_path)
                logging.debug(f"Test file cleaned up: {test_file_path}")
        except Exception as e:
            # Log warning but don't fail - cleanup is best effort
            logging.warning(f"Could not clean up test file {test_file_path}: {e}")

    def _evaluate_status(
        self,
        free_gb: float,
        warning_threshold_gb: float,
        critical_threshold_gb: float,
        is_accessible: bool,
        has_write_access: bool,
    ) -> StorageStatus:
        """
        Evaluate storage status based on all metrics.

        Priority order (most severe first):
        1. CRITICAL: No write access OR below critical space threshold
        2. ERROR: Path not accessible
        3. WARNING: Below warning space threshold
        4. OK: All checks passed

        Args:
            free_gb: Available space in GB
            warning_threshold_gb: Warning threshold
            critical_threshold_gb: Critical threshold
            is_accessible: Whether path is accessible
            has_write_access: Whether write access is available

        Returns:
            StorageStatus enum value
        """
        # Path not accessible is ERROR level
        if not is_accessible:
            return StorageStatus.ERROR

        # No write access is CRITICAL
        if not has_write_access:
            return StorageStatus.CRITICAL

        # Below critical space threshold is CRITICAL
        if free_gb < critical_threshold_gb:
            return StorageStatus.CRITICAL

        # Below warning space threshold is WARNING
        if free_gb < warning_threshold_gb:
            return StorageStatus.WARNING

        # All checks passed
        return StorageStatus.OK
