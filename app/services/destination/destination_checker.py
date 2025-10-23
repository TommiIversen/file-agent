"""
Destination Checker - validates destination availability with caching.
"""

import asyncio
import logging
import time
import uuid
import glob
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiofiles


@dataclass
class DestinationCheckResult:
    """Result of destination availability check."""

    is_available: bool
    checked_at: datetime
    error_message: Optional[str] = None
    test_file_path: Optional[str] = None


class DestinationChecker:
    """Checks destination availability with TTL-based caching and concurrent access protection."""

    def __init__(
            self,
            destination_path: Path,
            cache_ttl_seconds: float = 5.0,
            storage_monitor=None,
    ):
        self.destination_path = destination_path
        self.cache_ttl_seconds = cache_ttl_seconds
        self._storage_monitor = storage_monitor

        self._cached_result: Optional[DestinationCheckResult] = None
        self._cache_timestamp = 0.0
        self._check_lock = asyncio.Lock()

        logging.debug(f"DestinationChecker initialized for: {destination_path}")
        if storage_monitor:
            logging.debug("Connected to StorageMonitorService for instant updates")

    async def is_available(self, force_refresh: bool = False) -> bool:
        """Check if destination is available, using cache if valid."""
        if not force_refresh and self._is_cache_valid():
            logging.debug("Using cached destination availability result")
            return self._cached_result.is_available

        async with self._check_lock:
            if not force_refresh and self._is_cache_valid():
                return self._cached_result.is_available

            logging.debug("Performing fresh destination availability check")
            result = await self._perform_availability_check()

            self._cached_result = result
            self._cache_timestamp = time.time()

            await self._trigger_storage_update_if_changed(result.is_available)

            return result.is_available

    async def test_write_access(self, dest_path: Optional[Path] = None) -> bool:
        """Test write access to destination directory."""
        target_path = dest_path or self.destination_path

        try:
            test_file = target_path / f".file_agent_write_test_{uuid.uuid4().hex[:8]}"

            async with aiofiles.open(test_file, "w") as f:
                await f.write("write_test")

            try:
                test_file.unlink()
                logging.debug(f"Write access test successful: {target_path}")
                return True
            except Exception as cleanup_error:
                logging.warning(f"Could not cleanup test file: {cleanup_error}")
                return True

        except Exception as e:
            logging.warning(f"Write access test failed for {target_path}: {e}")
            return False

    def cache_result(self, result: bool, error_message: Optional[str] = None) -> None:
        """Manually cache a destination check result."""
        self._cached_result = DestinationCheckResult(
            is_available=result, checked_at=datetime.now(), error_message=error_message
        )
        self._cache_timestamp = time.time()

        logging.debug(f"Manually cached destination result: {result}")

    def get_cached_result(self) -> Optional[DestinationCheckResult]:
        """Get current cached result if valid."""
        if self._is_cache_valid():
            return self._cached_result
        return None

    def clear_cache(self) -> None:
        """Clear cached results (useful for testing)."""
        self._cached_result = None
        self._cache_timestamp = 0.0
        logging.debug("Destination checker cache cleared")

    def get_cache_info(self) -> dict:
        """Get information about cache state (for debugging/monitoring)."""
        return {
            "has_cached_result": self._cached_result is not None,
            "cache_timestamp": self._cache_timestamp,
            "cache_age_seconds": time.time() - self._cache_timestamp
            if self._cache_timestamp > 0
            else None,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "is_cache_valid": self._is_cache_valid(),
            "destination_path": str(self.destination_path),
        }

    async def cleanup_old_test_files(self) -> int:
        """
        Ryd op i gamle test-filer i destination directory.
        
        Returns:
            Antal filer der blev slettet
        """
        cleaned_count = 0
        try:
            # Find alle test-filer der matcher vores pattern (.file_agent_test_* og .file_agent_write_test_*)
            patterns = [
                str(self.destination_path / ".file_agent_test_*"),
                str(self.destination_path / ".file_agent_write_test_*")
            ]
            
            test_files = []
            for pattern in patterns:
                test_files.extend(glob.glob(pattern))
            
            logging.debug(f"Found {len(test_files)} old test files to clean up in {self.destination_path}")
            
            for test_file in test_files:
                try:
                    if os.path.exists(test_file):
                        os.remove(test_file)
                        cleaned_count += 1
                        logging.debug(f"Cleaned up old test file: {test_file}")
                except Exception as e:
                    logging.warning(f"Could not clean up old test file {test_file}: {e}")
                    
            if cleaned_count > 0:
                logging.info(f"Cleaned up {cleaned_count} old test files from {self.destination_path}")
                
        except Exception as e:
            logging.error(f"Error during old test files cleanup in {self.destination_path}: {e}")
            
        return cleaned_count

    async def _trigger_storage_update_if_changed(self, current_available: bool) -> None:
        """Trigger storage monitor update if availability status changed."""
        if not self._storage_monitor:
            return

        previous_result = None
        if hasattr(self, "_previous_result_for_comparison"):
            previous_result = self._previous_result_for_comparison

        if previous_result is None or previous_result != current_available:
            logging.debug(
                f"Destination availability changed: {previous_result} -> {current_available}"
            )
            try:
                await self._storage_monitor.trigger_immediate_check("destination")
                logging.debug("Triggered immediate storage monitor update")
            except Exception as e:
                logging.warning(f"Failed to trigger storage monitor update: {e}")

        self._previous_result_for_comparison = current_available

    def _is_cache_valid(self) -> bool:
        """Check if cached result is still valid based on TTL."""
        if self._cached_result is None:
            return False

        age = time.time() - self._cache_timestamp
        return age < self.cache_ttl_seconds

    async def _perform_availability_check(self) -> DestinationCheckResult:
        """Perform the actual destination availability check."""
        try:
            if self._storage_monitor:
                storage_info = self._storage_monitor.get_destination_info()

                if not storage_info:
                    error_msg = "Destination storage information not available from StorageMonitor"
                    logging.warning(error_msg)
                    return DestinationCheckResult(
                        is_available=False,
                        checked_at=datetime.now(),
                        error_message=error_msg,
                    )

                if not storage_info.is_accessible:
                    error_msg = f"Destination directory not accessible according to StorageMonitor: {storage_info.error_message or 'Unknown reason'}"
                    logging.warning(error_msg)
                    return DestinationCheckResult(
                        is_available=False,
                        checked_at=datetime.now(),
                        error_message=error_msg,
                    )

                if not storage_info.has_write_access:
                    error_msg = (
                        "Destination directory not writable according to StorageMonitor"
                    )
                    logging.warning(error_msg)
                    return DestinationCheckResult(
                        is_available=False,
                        checked_at=datetime.now(),
                        error_message=error_msg,
                    )
                
                # StorageMonitor confirms destination is good
                logging.debug("Destination availability confirmed by StorageMonitor")
                return DestinationCheckResult(
                    is_available=True, checked_at=datetime.now()
                )
            else:
                # No StorageMonitor - perform direct check with async safety
                logging.warning(
                    "StorageMonitor not available - performing direct directory check"
                )
                
                def _sync_directory_check():
                    if not self.destination_path.exists():
                        try:
                            self.destination_path.mkdir(parents=True, exist_ok=True)
                            logging.info(
                                f"Created missing destination directory: {self.destination_path}"
                            )
                        except Exception as e:
                            error_msg = f"Destination directory does not exist and could not create: {self.destination_path} - {e}"
                            logging.error(error_msg)
                            return False, error_msg
                    
                    if not self.destination_path.is_dir():
                        error_msg = f"Destination is not a directory: {self.destination_path}"
                        return False, error_msg
                    
                    return True, None
                
                try:
                    success, error_msg = await asyncio.to_thread(_sync_directory_check)
                    if not success:
                        return DestinationCheckResult(
                            is_available=False,
                            checked_at=datetime.now(),
                            error_message=error_msg,
                        )
                except Exception as e:
                    error_msg = f"Directory check failed: {e}"
                    logging.error(error_msg)
                    return DestinationCheckResult(
                        is_available=False,
                        checked_at=datetime.now(),
                        error_message=error_msg,
                    )

                # Directory exists, now test write access
                test_file = (
                        self.destination_path / f".file_agent_test_{uuid.uuid4().hex[:8]}"
                )

                try:
                    async with aiofiles.open(test_file, "w") as f:
                        await f.write("availability_test")

                    # Cleanup test file using modern asyncio.to_thread
                    try:
                        await asyncio.to_thread(test_file.unlink)
                    except Exception as cleanup_error:
                        logging.debug(
                            f"Could not cleanup test file (ignoring): {cleanup_error}"
                        )

                    logging.debug(
                        f"Destination availability check passed: {self.destination_path}"
                    )
                    return DestinationCheckResult(
                        is_available=True,
                        checked_at=datetime.now(),
                        test_file_path=str(test_file),
                    )

                except Exception as write_error:
                    error_msg = f"Cannot write to destination: {write_error}"
                    logging.warning(error_msg)
                    return DestinationCheckResult(
                        is_available=False,
                        checked_at=datetime.now(),
                        error_message=error_msg,
                        test_file_path=str(test_file),
                    )

        except Exception as e:
            error_msg = f"Error during destination availability check: {e}"
            logging.error(error_msg)
            return DestinationCheckResult(
                is_available=False, checked_at=datetime.now(), error_message=error_msg
            )
