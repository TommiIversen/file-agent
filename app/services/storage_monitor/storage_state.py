"""
Storage State Management for File Transfer Agent.

This class is responsible solely for maintaining storage state cache and 
providing state-related operations, adhering to SRP.
"""

from typing import Optional

from ...models import StorageInfo, StorageStatus
from ...logging_config import get_app_logger


class StorageState:
    """
    Manages storage state cache and status tracking.
    
    Single Responsibility: Storage state management ONLY
    Size: <150 lines (currently ~80 lines)
    
    This class is responsible solely for storage state caching, adhering to SRP.
    """
    
    def __init__(self):
        """Initialize storage state manager."""
        # This class is responsible solely for storage state caching, adhering to SRP
        self._source_info: Optional[StorageInfo] = None
        self._destination_info: Optional[StorageInfo] = None
        self._logger = get_app_logger()
        
    def update_source_info(self, info: StorageInfo) -> bool:
        """
        Update source storage info and detect changes.
        
        Args:
            info: New source storage information
            
        Returns:
            True if status changed, False otherwise
        """
        old_status = self._source_info.status if self._source_info else None
        self._source_info = info
        return old_status != info.status
    
    def update_destination_info(self, info: StorageInfo) -> bool:
        """
        Update destination storage info and detect changes.
        
        Args:
            info: New destination storage information
            
        Returns:
            True if status changed, False otherwise
        """
        old_status = self._destination_info.status if self._destination_info else None
        self._destination_info = info
        return old_status != info.status
    
    def get_source_info(self) -> Optional[StorageInfo]:
        """Get current source storage info."""
        return self._source_info
    
    def get_destination_info(self) -> Optional[StorageInfo]:
        """Get current destination storage info."""
        return self._destination_info
    
    def get_overall_status(self) -> StorageStatus:
        """
        Get overall storage status (highest priority status).
        
        Returns:
            Worst storage status across both source and destination
        """
        statuses = set()
        
        if self._source_info:
            statuses.add(self._source_info.status)
            
        if self._destination_info:
            statuses.add(self._destination_info.status)
        
        # Return highest priority status
        priority_order = [
            StorageStatus.CRITICAL,
            StorageStatus.ERROR, 
            StorageStatus.WARNING,
            StorageStatus.OK
        ]
        
        for status in priority_order:
            if status in statuses:
                return status
        
        return StorageStatus.OK
    
    def get_directory_readiness(self) -> dict:
        """
        Get current directory readiness state - cached, no I/O operations.
        
        This provides consumers with instant access to directory state without
        performing any I/O operations, following the Central Storage Authority pattern.
        
        Returns:
            Dictionary with directory readiness information
        """
        return {
            "source_ready": self._source_info.is_accessible if self._source_info else False,
            "destination_ready": self._destination_info.is_accessible if self._destination_info else False,
            "source_writable": (self._source_info.has_write_access if self._source_info else False),
            "destination_writable": (self._destination_info.has_write_access if self._destination_info else False),
            "last_source_check": self._source_info.last_checked if self._source_info else None,
            "last_destination_check": self._destination_info.last_checked if self._destination_info else None,
            "overall_ready": (
                (self._source_info.is_accessible if self._source_info else False) and 
                (self._destination_info.is_accessible if self._destination_info else False)
            )
        }
    
    def get_monitoring_status(self) -> dict:
        """
        Get monitoring service status for health checks.
        
        Returns:
            Dictionary with service status information
        """
        return {
            "source_monitored": self._source_info is not None,
            "destination_monitored": self._destination_info is not None,
            "overall_status": self.get_overall_status().value
        }