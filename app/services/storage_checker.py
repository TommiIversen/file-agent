import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Tuple
from uuid import uuid4
import asyncio

import aiofiles
import aiofiles.os

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
        """Check if path is accessible using modern asyncio.to_thread."""
        try:
            def _sync_check():
                path_obj = Path(path)
                return path_obj.exists() and path_obj.is_dir()
            
            return await asyncio.wait_for(
                asyncio.to_thread(_sync_check),
                timeout=5.0  # 5 second timeout
            )
        except asyncio.TimeoutError:
            logging.warning(f"Accessibility check timed out for {path}")
            return False
        except Exception as e:
            logging.debug(f"Accessibility check failed for {path}: {e}")
            return False

    async def _get_disk_usage(self, path: str) -> Tuple[float, float, float]:
        """Get disk usage using modern asyncio.to_thread."""
        try:
            def _sync_disk_usage():
                total_bytes, used_bytes, free_bytes = shutil.disk_usage(path)
                gb_divisor = 1024 ** 3
                total_gb = total_bytes / gb_divisor
                used_gb = used_bytes / gb_divisor
                free_gb = free_bytes / gb_divisor
                return free_gb, total_gb, used_gb
                
            free_gb, total_gb, used_gb = await asyncio.wait_for(
                asyncio.to_thread(_sync_disk_usage),
                timeout=10.0  # 10 second timeout
            )

            logging.debug(
                f"Disk usage for {path}: {free_gb:.1f}GB free of {total_gb:.1f}GB total"
            )
            return free_gb, total_gb, used_gb
        except asyncio.TimeoutError:
            logging.error(f"Disk usage check timed out for {path}")
            raise StorageAccessError(f"Disk usage check timed out for {path}")
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
        """Cleanup test file using aiofiles."""
        try:
            if await aiofiles.os.path.exists(test_file_path):
                await aiofiles.os.remove(test_file_path)
                logging.debug(f"Test file cleaned up: {test_file_path}")
        except Exception as e:
            logging.warning(f"Could not clean up test file {test_file_path}: {e}")

    async def cleanup_old_test_files(self, directory: str) -> int:
        """
        Ryd op i gamle test-filer i det specificerede directory.

        Args:
            directory: Stien til directory der skal ryddes op i

        Returns:
            Antal filer der blev slettet
        """
        cleaned_count = 0
        try:
            if not await aiofiles.os.path.isdir(directory):
                logging.debug(f"Cleanup directory does not exist or is not a directory: {directory}")
                return 0

            async for entry in await aiofiles.os.scandir(directory):
                if entry.is_file() and entry.name.startswith(self._test_file_prefix) and entry.name.endswith(".tmp"):
                    try:
                        await aiofiles.os.remove(entry.path)
                        cleaned_count += 1
                        logging.debug(f"Cleaned up old test file: {entry.path}")
                    except Exception as e:
                        logging.warning(f"Could not clean up old test file {entry.path}: {e}")

            if cleaned_count > 0:
                logging.info(f"Cleaned up {cleaned_count} old test files from {directory}")

        except Exception as e:
            logging.error(f"Error during old test files cleanup in {directory}: {e}")

        return cleaned_count

    async def cleanup_all_test_files(self, source_dir: str, dest_dir: str = None) -> int:
        """
        Ryd op i gamle test-filer i både source og destination directories.

        Args:
            source_dir: Source directory sti
            dest_dir: Destination directory sti (optional)

        Returns:
            Total antal filer der blev slettet
        """
        total_cleaned = 0

        # Cleanup source directory
        total_cleaned += await self.cleanup_old_test_files(source_dir)

        # Cleanup destination directory hvis angivet
        if dest_dir:
            try:
                if await aiofiles.os.path.isdir(dest_dir):
                    total_cleaned += await self.cleanup_old_test_files(dest_dir)
            except Exception as e:
                logging.warning(f"Destination directory check failed for {dest_dir}: {e}")

        return total_cleaned

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
