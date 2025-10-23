"""
Network Error Detector for immediate failure detection in copy strategies.

This module provides utilities to detect network errors early in copy operations,
enabling fail-fast behavior instead of waiting for the full operation to fail.

Strategy:
1. Primary detection: Analyze copy operation errors for network patterns
2. Secondary check: Lightweight read-only connectivity checks (no test file writing)
3. Fail-fast: Immediately classify and escalate network errors
"""

import errno
import logging
import time
from pathlib import Path


class NetworkError(Exception):
    """Custom exception for network-related errors in copy operations."""
    pass


class NetworkErrorDetector:
    """Detects network errors early during copy operations for fail-fast behavior."""
    
    # Network error indicators to check for
    NETWORK_ERROR_STRINGS = {
        "input/output error", "errno 5", "connection refused", "network is unreachable",
        "no route to host", "connection timed out", "broken pipe", "errno 32", "errno 110",
        "errno 111", "smb error", "cifs error", "mount_smbfs", "network mount", "permission denied",
        "invalid argument", "errno 22", "network path was not found", "winerror 53", 
        "the network name cannot be found", "winerror 67", "the network location cannot be reached",
        "winerror 1231", "access is denied", "errno 13"
    }
    
    # Network-related errno codes (including Windows-specific)
    NETWORK_ERRNO_CODES = {
        errno.EIO, errno.ECONNREFUSED, errno.ETIMEDOUT, errno.ENETUNREACH,
        errno.EHOSTUNREACH, errno.EPIPE, errno.EACCES, errno.ENOTCONN, errno.ECONNRESET,
        errno.EINVAL,  # Can be network-related on Windows when destination unavailable
        errno.ENOENT,  # Network path not found
        errno.EACCES,  # Access denied (can be network mount issues)
        53, 67, 1231   # Windows-specific network error codes
    }
    
    def __init__(self, destination_path: str, check_interval_bytes: int = 10 * 1024 * 1024):
        """
        Initialize network error detector.
        
        Args:
            destination_path: Path to destination to monitor
            check_interval_bytes: Check connectivity every N bytes copied (default: 10MB)
        """
        self.destination_path = Path(destination_path)
        self.check_interval_bytes = check_interval_bytes
        self.last_check_bytes = 0
        self.last_check_time = time.time()
        
    def should_check_network(self, bytes_copied: int) -> bool:
        """Determine if we should check network connectivity."""
        return bytes_copied - self.last_check_bytes >= self.check_interval_bytes
        
    def check_destination_connectivity(self, bytes_copied: int) -> None:
        """
        Check if destination is still accessible using lightweight read-only operations.
        
        This approach avoids creating test files on the network during large
        copy operations, reducing I/O conflicts and improving performance.
        Uses directory listing instead of file creation for connectivity checks.
        
        Raises NetworkError if destination appears to be unreachable.
        """
        if not self.should_check_network(bytes_copied):
            return
            
        try:
            # Lightweight connectivity check - only read operations, no writing
            dest_parent = self.destination_path.parent
            
            # Quick stat check - just read directory metadata
            if not dest_parent.exists():
                raise NetworkError(f"Destination directory no longer accessible: {dest_parent}")
                
            # Try to list directory contents (read-only operation)
            try:
                # This will fail fast if network is down, but doesn't write anything
                list(dest_parent.iterdir())
            except Exception as e:
                error_str = str(e).lower()
                if self._is_network_error_string(error_str):
                    raise NetworkError(f"Network connectivity lost during directory read: {e}")
                # If it's not a network error, continue (might be permissions etc.)
                
            self.last_check_bytes = bytes_copied
            self.last_check_time = time.time()
            
        except NetworkError:
            # Re-raise network errors
            raise
        except Exception as e:
            # Check if this looks like a network error
            error_str = str(e).lower()
            if self._is_network_error_string(error_str) or self._is_network_errno(e):
                raise NetworkError(f"Network error during connectivity check: {e}")
            # Otherwise, log but don't fail the copy for non-network issues
            logging.debug(f"Non-network error during connectivity check: {e}")
            
    def _is_network_error_string(self, error_str: str) -> bool:
        """Check if error string indicates network issue."""
        return any(indicator in error_str for indicator in self.NETWORK_ERROR_STRINGS)
        
    def _is_network_errno(self, error: Exception) -> bool:
        """Check if error has network-related errno."""
        return hasattr(error, "errno") and error.errno in self.NETWORK_ERRNO_CODES
        
    def check_write_error(self, error: Exception, operation: str = "write") -> None:
        """
        Check if a write error is network-related and raise NetworkError if so.
        
        Args:
            error: The exception that occurred
            operation: Description of the operation that failed
        """
        error_str = str(error).lower()
        
        if self._is_network_error_string(error_str) or self._is_network_errno(error):
            raise NetworkError(f"Network error during {operation}: {error}")