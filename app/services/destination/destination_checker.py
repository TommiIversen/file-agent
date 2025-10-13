"""
Destination Checker Strategy for File Transfer Agent.

Part of Phase 2.1 refactoring: Extract Strategy Classes from FileCopyService.

This module implements destination availability checking with caching, concurrent access
protection, and proper error handling. Extracted from FileCopyService to follow
Single Responsibility Principle.

Design:
- Handles destination directory existence and write access validation
- Implements TTL-based caching to avoid redundant I/O operations  
- Thread-safe concurrent access protection with asyncio.Lock
- Configurable cache timeout and cleanup behavior
"""

import asyncio
import aiofiles
import logging
import time
import uuid
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class DestinationCheckResult:
    """Result of destination availability check."""
    is_available: bool
    checked_at: datetime
    error_message: Optional[str] = None
    test_file_path: Optional[str] = None


class DestinationChecker:
    """
    Strategy class for checking destination availability with caching.
    
    Responsibilities:
    1. Validate destination directory existence and permissions
    2. Test write access using temporary test files
    3. Cache results with configurable TTL to reduce I/O overhead
    4. Handle concurrent access from multiple workers safely
    5. Provide detailed error reporting for troubleshooting
    """
    
    def __init__(self, destination_path: Path, cache_ttl_seconds: float = 5.0, storage_monitor=None):
        """
        Initialize DestinationChecker.
        
        Args:
            destination_path: Path to destination directory to check
            cache_ttl_seconds: Time-to-live for cached results in seconds
            storage_monitor: Optional StorageMonitorService for triggering immediate updates
        """
        self.destination_path = destination_path
        self.cache_ttl_seconds = cache_ttl_seconds
        self._storage_monitor = storage_monitor
        
        # Caching state
        self._cached_result: Optional[DestinationCheckResult] = None
        self._cache_timestamp = 0.0
        
        # Concurrent access protection
        self._check_lock = asyncio.Lock()
        
        # Logging
        
        
        logging.debug(f"DestinationChecker initialized for: {destination_path}")
        logging.debug(f"Cache TTL: {cache_ttl_seconds} seconds")
        if storage_monitor:
            logging.debug("Connected to StorageMonitorService for instant updates")
    
    async def is_available(self, force_refresh: bool = False) -> bool:
        """
        Check if destination is available, using cache if valid.
        
        Args:
            force_refresh: If True, bypass cache and perform fresh check
            
        Returns:
            True if destination is available and writable
        """
        if not force_refresh and self._is_cache_valid():
            logging.debug("Using cached destination availability result")
            return self._cached_result.is_available
        
        # Use lock to prevent multiple concurrent checks
        async with self._check_lock:
            # Double-check pattern: another coroutine might have updated cache
            if not force_refresh and self._is_cache_valid():
                return self._cached_result.is_available
            
            logging.debug("Performing fresh destination availability check")
            result = await self._perform_availability_check()
            
            # Update cache
            self._cached_result = result
            self._cache_timestamp = time.time()
            
            # Trigger storage monitor update if availability changed
            await self._trigger_storage_update_if_changed(result.is_available)
            
            return result.is_available
    
    async def test_write_access(self, dest_path: Optional[Path] = None) -> bool:
        """
        Test write access to destination directory.
        
        Args:
            dest_path: Specific path to test (defaults to configured destination)
            
        Returns:
            True if write access is available
        """
        target_path = dest_path or self.destination_path
        
        try:
            # Create unique test file to avoid conflicts
            test_file = target_path / f".file_agent_write_test_{uuid.uuid4().hex[:8]}"
            
            # Test write operation
            async with aiofiles.open(test_file, 'w') as f:
                await f.write("write_test")
            
            # Cleanup test file
            try:
                test_file.unlink()
                logging.debug(f"Write access test successful: {target_path}")
                return True
            except Exception as cleanup_error:
                logging.warning(f"Could not cleanup test file: {cleanup_error}")
                return True  # Write was successful even if cleanup failed
                
        except Exception as e:
            logging.warning(f"Write access test failed for {target_path}: {e}")
            return False
    
    def cache_result(self, result: bool, error_message: Optional[str] = None) -> None:
        """
        Manually cache a destination check result.
        
        Args:
            result: Whether destination is available
            error_message: Optional error message if result is False
        """
        self._cached_result = DestinationCheckResult(
            is_available=result,
            checked_at=datetime.now(),
            error_message=error_message
        )
        self._cache_timestamp = time.time()
        
        logging.debug(f"Manually cached destination result: {result}")
    
    def get_cached_result(self) -> Optional[DestinationCheckResult]:
        """
        Get current cached result if valid.
        
        Returns:
            Cached result if valid, None otherwise
        """
        if self._is_cache_valid():
            return self._cached_result
        return None
    
    def clear_cache(self) -> None:
        """Clear cached results (useful for testing)."""
        self._cached_result = None
        self._cache_timestamp = 0.0
        logging.debug("Destination checker cache cleared")
    
    def get_cache_info(self) -> dict:
        """
        Get information about cache state (for debugging/monitoring).
        
        Returns:
            Dictionary with cache information
        """
        return {
            "has_cached_result": self._cached_result is not None,
            "cache_timestamp": self._cache_timestamp,
            "cache_age_seconds": time.time() - self._cache_timestamp if self._cache_timestamp > 0 else None,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "is_cache_valid": self._is_cache_valid(),
            "destination_path": str(self.destination_path)
        }
    
    async def _trigger_storage_update_if_changed(self, current_available: bool) -> None:
        """
        Trigger storage monitor update if availability status changed.
        
        Args:
            current_available: Current availability status
        """
        if not self._storage_monitor:
            return
            
        # Check if status actually changed from previous cached result
        previous_result = None
        if hasattr(self, '_previous_result_for_comparison'):
            previous_result = self._previous_result_for_comparison
            
        # If this is the first check or status changed, trigger update
        if (previous_result is None or 
            previous_result != current_available):
            
            logging.debug(f"Destination availability changed: {previous_result} -> {current_available}")
            try:
                await self._storage_monitor.trigger_immediate_check("destination")
                logging.debug("Triggered immediate storage monitor update")
            except Exception as e:
                logging.warning(f"Failed to trigger storage monitor update: {e}")
        
        # Store current status for next comparison
        self._previous_result_for_comparison = current_available

    # Private methods
    
    def _is_cache_valid(self) -> bool:
        """Check if cached result is still valid based on TTL."""
        if self._cached_result is None:
            return False
        
        age = time.time() - self._cache_timestamp
        return age < self.cache_ttl_seconds
    
    async def _perform_availability_check(self) -> DestinationCheckResult:
        """
        Perform the actual destination availability check.
        
        Returns:
            DestinationCheckResult with check details
        """
        try:
            # Enhanced: Query StorageMonitorService instead of direct I/O operations
            # This follows Central Storage Authority pattern and eliminates race conditions
            if self._storage_monitor:
                storage_info = self._storage_monitor.get_destination_info()
                
                if not storage_info:
                    error_msg = "Destination storage information not available from StorageMonitor"
                    logging.warning(error_msg)
                    return DestinationCheckResult(
                        is_available=False,
                        checked_at=datetime.now(),
                        error_message=error_msg
                    )
                
                if not storage_info.is_accessible:
                    error_msg = f"Destination directory not accessible according to StorageMonitor: {storage_info.error_message or 'Unknown reason'}"
                    logging.warning(error_msg)
                    return DestinationCheckResult(
                        is_available=False,
                        checked_at=datetime.now(),
                        error_message=error_msg
                    )
                
                if not storage_info.has_write_access:
                    error_msg = "Destination directory not writable according to StorageMonitor"
                    logging.warning(error_msg)
                    return DestinationCheckResult(
                        is_available=False,
                        checked_at=datetime.now(),
                        error_message=error_msg
                    )
            else:
                # Fallback for backward compatibility (should not happen in production)
                logging.warning("StorageMonitor not available - performing direct directory check")
                if not self.destination_path.exists():
                    error_msg = f"Destination directory does not exist and StorageMonitor not available: {self.destination_path}"
                    logging.error(error_msg)
                    return DestinationCheckResult(
                        is_available=False,
                        checked_at=datetime.now(),
                        error_message=error_msg
                    )

                if not self.destination_path.is_dir():
                    error_msg = f"Destination is not a directory: {self.destination_path}"
                    logging.warning(error_msg)
                    return DestinationCheckResult(
                        is_available=False,
                        checked_at=datetime.now(),
                        error_message=error_msg
                    )
            
            # If we reach here with StorageMonitor, destination is ready
            if self._storage_monitor:
                logging.debug("Destination availability confirmed by StorageMonitor")
                return DestinationCheckResult(
                    is_available=True,
                    checked_at=datetime.now()
                )
            else:
                # Fallback: Perform basic write test if StorageMonitor unavailable
                test_file = self.destination_path / f".file_agent_test_{uuid.uuid4().hex[:8]}"
                
                try:
                    async with aiofiles.open(test_file, 'w') as f:
                        await f.write("availability_test")
                    
                    # Cleanup test file
                    try:
                        test_file.unlink()
                    except Exception as cleanup_error:
                        logging.debug(f"Could not cleanup test file (ignoring): {cleanup_error}")
                    
                    logging.debug(f"Destination availability check passed: {self.destination_path}")
                    return DestinationCheckResult(
                        is_available=True,
                        checked_at=datetime.now(),
                        test_file_path=str(test_file)
                    )
                    
                except Exception as write_error:
                    error_msg = f"Cannot write to destination: {write_error}"
                    logging.warning(error_msg)
                    return DestinationCheckResult(
                        is_available=False,
                        checked_at=datetime.now(),
                        error_message=error_msg,
                        test_file_path=str(test_file)
                    )
                
        except Exception as e:
            error_msg = f"Error during destination availability check: {e}"
            logging.error(error_msg)
            return DestinationCheckResult(
                is_available=False,
                checked_at=datetime.now(),
                error_message=error_msg
            )
