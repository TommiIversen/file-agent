"""
Job Error Classifier for File Transfer Agent.

Intelligently classifies copy errors to determine if they should trigger:
- Immediate FAILED status (local/source errors)
- Pause for resume (destination/network errors)

This service adheres to SRP by focusing solely on error classification logic.
"""

import logging
import errno
import os
from typing import Optional, Tuple
from pathlib import Path

from app.services.storage_monitor.storage_monitor import StorageMonitorService
from app.models import StorageStatus


class JobErrorClassifier:
    """
    Classifies copy errors to determine appropriate handling strategy.
    
    Responsible for:
    1. Network/destination error detection
    2. Source/local error detection  
    3. Error classification for pause vs fail decision
    """
    
    def __init__(self, storage_monitor: StorageMonitorService):
        """
        Initialize error classifier.
        
        Args:
            storage_monitor: Storage monitor for destination status checks
        """
        self.storage_monitor = storage_monitor
        self._logger = logging.getLogger("app.job_error_classifier")
        
    def classify_copy_error(self, error: Exception, file_path: str) -> Tuple[bool, str]:
        """
        Classify copy error to determine if it should pause or fail.
        
        Args:
            error: The exception that occurred during copy
            file_path: Path to the file being copied
            
        Returns:
            Tuple of (should_pause, reason):
            - should_pause: True if error should trigger pause, False for immediate fail
            - reason: Human-readable reason for the classification
        """
        error_str = str(error).lower()
        
        # Check if destination is currently having issues
        destination_info = self.storage_monitor.get_destination_info()
        if destination_info and destination_info.status in [StorageStatus.ERROR, StorageStatus.CRITICAL]:
            return True, f"Destination unavailable (status: {destination_info.status.value})"
        
        # Check for network/I/O errors that typically indicate destination issues
        network_error_indicators = [
            "input/output error",
            "errno 5",
            "connection refused", 
            "network is unreachable",
            "no route to host",
            "connection timed out",
            "broken pipe",
            "errno 32",  # Broken pipe
            "errno 110", # Connection timed out
            "errno 111", # Connection refused
            "smb error",
            "cifs error",
            "mount_smbfs",
            "network mount",
            "permission denied" # Often network auth issues
        ]
        
        for indicator in network_error_indicators:
            if indicator in error_str:
                self._logger.warning(
                    f"🔍 NETWORK ERROR DETECTED: {file_path} - {indicator} → PAUSE for resume"
                )
                return True, f"Network error detected: {indicator}"
        
        # Check for specific OS errno codes
        if hasattr(error, 'errno'):
            errno_code = error.errno
            
            # Network/destination related errno codes
            if errno_code in [
                errno.EIO,          # 5: Input/output error
                errno.ECONNREFUSED, # 111: Connection refused  
                errno.ETIMEDOUT,    # 110: Connection timed out
                errno.ENETUNREACH,  # 101: Network is unreachable
                errno.EHOSTUNREACH, # 113: No route to host
                errno.EPIPE,        # 32: Broken pipe
                errno.EACCES,       # 13: Permission denied (often network auth)
                errno.ENOTCONN,     # 107: Transport endpoint not connected
                errno.ECONNRESET,   # 104: Connection reset by peer
            ]:
                self._logger.warning(
                    f"🔍 NETWORK ERRNO DETECTED: {file_path} - errno {errno_code} → PAUSE for resume"
                )
                return True, f"Network errno {errno_code}: {os.strerror(errno_code)}"
        
        # Source file issues - these should fail immediately
        source_error_indicators = [
            "no such file or directory",
            "errno 2",   # ENOENT
            "file not found",
            "source file",
            "input file"
        ]
        
        for indicator in source_error_indicators:
            if indicator in error_str:
                self._logger.info(
                    f"📁 SOURCE ERROR DETECTED: {file_path} - {indicator} → FAIL immediately"
                )
                return False, f"Source error: {indicator}"
        
        # Check if source file still exists
        try:
            source_path = Path(file_path)
            if not source_path.exists():
                self._logger.info(
                    f"📁 SOURCE MISSING: {file_path} - source file deleted → FAIL immediately"
                )
                return False, "Source file no longer exists"
        except Exception as check_error:
            self._logger.warning(f"Could not check source file existence: {check_error}")
        
        # Default: If unsure and destination seems OK, treat as local error
        self._logger.warning(
            f"❓ UNKNOWN ERROR TYPE: {file_path} - {error_str} → defaulting to PAUSE for safety"
        )
        return True, f"Unknown error (defaulting to pause): {str(error)}"
    
    def log_classification_decision(self, file_path: str, should_pause: bool, reason: str) -> None:
        """
        Log the classification decision for debugging.
        
        Args:
            file_path: Path to the file
            should_pause: Whether the error should trigger pause
            reason: Reason for the decision
        """
        action = "PAUSE" if should_pause else "FAIL"
        self._logger.info(f"🎯 ERROR CLASSIFICATION: {Path(file_path).name} → {action} ({reason})")