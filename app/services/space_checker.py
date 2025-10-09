"""
Space Checker Service for File Transfer Agent.

Clean utility service for pre-flight disk space checking.
Follows Single Responsibility Principle - only checks space availability.
"""

from typing import Optional

from ..config import Settings
from ..logging_config import get_app_logger
from ..models import SpaceCheckResult
from ..services.storage_monitor import StorageMonitorService


class SpaceChecker:
    """
    Utility service for checking if destination has sufficient space for file operations.
    
    Responsibilities:
    - Pre-flight space checking before file copying
    - Safety margin calculations  
    - Temporary vs permanent shortage detection
    - Clean, reusable space validation logic
    
    Dependencies:
    - StorageMonitorService (for current space info)
    - Settings (for safety margins and thresholds)
    
    Design Principles:
    - Single Responsibility: Only handles space checking
    - No side effects: Pure checking logic
    - Dependency Injection: Receives dependencies via constructor
    """
    
    def __init__(self, settings: Settings, storage_monitor: StorageMonitorService):
        """
        Initialize SpaceChecker with dependencies.
        
        Args:
            settings: Application configuration with space thresholds
            storage_monitor: Service providing real-time storage information
        """
        self._settings = settings
        self._storage_monitor = storage_monitor
        self._logger = get_app_logger()
        
        self._logger.debug("SpaceChecker initialized")
    
    def check_space_for_file(self, file_size_bytes: int) -> SpaceCheckResult:
        """
        Check if destination has sufficient space for a file.
        
        Performs comprehensive space check including:
        - Current available space
        - Required space (file + safety margin)
        - Minimum free space after copy
        
        Args:
            file_size_bytes: Size of file to be copied in bytes
            
        Returns:
            SpaceCheckResult with detailed space analysis
        """
        self._logger.debug(f"Checking space for file of {file_size_bytes} bytes")
        
        # Get current destination storage info
        storage_info = self._storage_monitor.get_destination_info()
        
        if not storage_info:
            return self._create_unavailable_result(file_size_bytes)
        
        if not storage_info.is_accessible:
            return self._create_inaccessible_result(file_size_bytes, storage_info.error_message)
        
        # Calculate space requirements
        available_bytes = int(storage_info.free_space_gb * (1024**3))
        safety_margin_bytes = int(self._settings.copy_safety_margin_gb * (1024**3))
        minimum_after_copy_bytes = int(self._settings.minimum_free_space_after_copy_gb * (1024**3))
        
        # Total required = file size + safety margin + minimum remaining
        required_bytes = file_size_bytes + safety_margin_bytes + minimum_after_copy_bytes
        
        # Check if we have sufficient space
        has_space = available_bytes >= required_bytes
        
        # Create detailed reason
        reason = self._create_space_reason(
            has_space=has_space,
            available_bytes=available_bytes,
            required_bytes=required_bytes,
            file_size_bytes=file_size_bytes,
            safety_margin_bytes=safety_margin_bytes,
            minimum_after_copy_bytes=minimum_after_copy_bytes
        )
        
        return SpaceCheckResult(
            has_space=has_space,
            available_bytes=available_bytes,
            required_bytes=required_bytes,
            file_size_bytes=file_size_bytes,
            safety_margin_bytes=safety_margin_bytes,
            reason=reason
        )
    
    def _create_unavailable_result(self, file_size_bytes: int) -> SpaceCheckResult:
        """Create result when storage info is unavailable"""
        return SpaceCheckResult(
            has_space=False,
            available_bytes=0,
            required_bytes=file_size_bytes,
            file_size_bytes=file_size_bytes,
            safety_margin_bytes=0,
            reason="Storage information unavailable - monitoring may not be running"
        )
    
    def _create_inaccessible_result(self, file_size_bytes: int, error_message: Optional[str]) -> SpaceCheckResult:
        """Create result when destination is not accessible"""
        reason = f"Destination not accessible: {error_message or 'Unknown error'}"
        
        return SpaceCheckResult(
            has_space=False,
            available_bytes=0,
            required_bytes=file_size_bytes,
            file_size_bytes=file_size_bytes,
            safety_margin_bytes=0,
            reason=reason
        )
    
    def _create_space_reason(self, has_space: bool, available_bytes: int, 
                           required_bytes: int, file_size_bytes: int,
                           safety_margin_bytes: int, minimum_after_copy_bytes: int) -> str:
        """
        Create human-readable reason for space check result.
        
        Args:
            has_space: Whether space is sufficient
            available_bytes: Available space
            required_bytes: Required space
            file_size_bytes: File size
            safety_margin_bytes: Safety margin
            minimum_after_copy_bytes: Minimum space to leave after copy
            
        Returns:
            Human-readable explanation
        """
        available_gb = available_bytes / (1024**3)
        required_gb = required_bytes / (1024**3)
        file_gb = file_size_bytes / (1024**3)
        
        if has_space:
            return (
                f"Sufficient space: {available_gb:.1f}GB available, "
                f"{required_gb:.1f}GB required for {file_gb:.1f}GB file"
            )
        else:
            shortage_gb = (required_bytes - available_bytes) / (1024**3)
            return (
                f"Insufficient space: {available_gb:.1f}GB available, "
                f"{required_gb:.1f}GB required (shortage: {shortage_gb:.1f}GB). "
                f"File: {file_gb:.1f}GB + safety margins"
            )
    
    def is_space_check_enabled(self) -> bool:
        """
        Check if pre-copy space checking is enabled.
        
        Returns:
            True if space checking should be performed
        """
        return self._settings.enable_pre_copy_space_check
    
    def get_space_settings_info(self) -> dict:
        """
        Get current space checking configuration for debugging.
        
        Returns:
            Dictionary with current space checking settings
        """
        return {
            "enabled": self._settings.enable_pre_copy_space_check,
            "safety_margin_gb": self._settings.copy_safety_margin_gb,
            "minimum_after_copy_gb": self._settings.minimum_free_space_after_copy_gb,
            "retry_delay_seconds": self._settings.space_retry_delay_seconds,
            "max_retries": self._settings.max_space_retries
        }