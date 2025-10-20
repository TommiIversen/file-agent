import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Tuple
from uuid import uuid4

import aiofiles

from ..models import StorageInfo, StorageStatus


class StorageAccessError(Exception):
    pass


class StorageChecker:
    def __init__(self, test_file_prefix: str = ".storage_test_"):
        self._test_file_prefix = test_file_prefix

    async def check_path(
            self, path: str, warning_threshold_gb: float, critical_threshold_gb: float
    ) -> StorageInfo:
        logging.debug(f"Checking storage path: {path}")

        is_accessible = False
        has_write_access = False
        free_gb = 0.0
        total_gb = 0.0
        used_gb = 0.0
        error_message = None

        try:
            is_accessible = await self._check_accessibility(path)
            if is_accessible:
                free_gb, total_gb, used_gb = await self._get_disk_usage(path)
                has_write_access = await self._check_write_access(path)
            else:
                error_message = f"Path {path} is not accessible"

        except Exception as e:
            error_message = f"Storage check error: {str(e)}"
            logging.error(f"Storage check failed for {path}: {e}")

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
        try:
            path_obj = Path(path)
            return path_obj.exists() and path_obj.is_dir()
        except Exception as e:
            logging.debug(f"Accessibility check failed for {path}: {e}")
            return False

    async def _get_disk_usage(self, path: str) -> Tuple[float, float, float]:
        try:
            total_bytes, used_bytes, free_bytes = shutil.disk_usage(path)

            gb_divisor = 1024 ** 3
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
        test_file_path = None

        try:
            test_file_path = await self._create_test_file(path)
            await self._cleanup_test_file(test_file_path)
            logging.debug(f"Write access verified for {path}")
            return True
        except Exception as e:
            logging.debug(f"Write access check failed for {path}: {e}")
            if test_file_path:
                await self._cleanup_test_file(test_file_path)
            return False

    async def _create_test_file(self, directory: str) -> str:
        test_filename = f"{self._test_file_prefix}{uuid4().hex}.tmp"
        test_file_path = os.path.join(directory, test_filename)

        try:
            async with aiofiles.open(test_file_path, "w") as f:
                await f.write("storage_write_test")
            logging.debug(f"Test file created: {test_file_path}")
            return test_file_path
        except Exception as e:
            raise StorageAccessError(f"Cannot create test file in {directory}: {e}")

    async def _cleanup_test_file(self, test_file_path: str) -> None:
        try:
            if os.path.exists(test_file_path):
                os.remove(test_file_path)
                logging.debug(f"Test file cleaned up: {test_file_path}")
        except Exception as e:
            logging.warning(f"Could not clean up test file {test_file_path}: {e}")

    def _evaluate_status(
            self,
            free_gb: float,
            warning_threshold_gb: float,
            critical_threshold_gb: float,
            is_accessible: bool,
            has_write_access: bool,
    ) -> StorageStatus:
        if not is_accessible:
            return StorageStatus.ERROR

        if not has_write_access:
            return StorageStatus.CRITICAL

        if free_gb < critical_threshold_gb:
            return StorageStatus.CRITICAL

        if free_gb < warning_threshold_gb:
            return StorageStatus.WARNING

        return StorageStatus.OK
