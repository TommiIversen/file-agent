"""
Storage Monitor Service for File Transfer Agent.

Clean orchestrator service that manages storage monitoring for source and destination.
Uses StorageChecker for actual health checks and manages state/scheduling/pub-sub.
"""

import asyncio
from typing import Optional

from .storage_checker import StorageChecker
from ..config import Settings
from ..logging_config import get_app_logger
from ..models import StorageInfo, StorageStatus, StorageUpdate


class StorageMonitorService:
    """
    Orchestrator for storage monitoring.
    
    Responsibilities:
    - Schedule periodic health checks using StorageChecker
    - Maintain current state for source and destination
    - Detect status changes and trigger notifications  
    - Integrate with WebSocketManager for real-time updates
    - Provide API-friendly data access methods
    
    Clean Architecture:
    - Uses StorageChecker for actual checking logic
    - Independent of StateManager (clean separation)
    - Direct WebSocket integration for pub-sub
    """
    
    def __init__(self, settings: Settings, storage_checker: StorageChecker, 
                 websocket_manager=None):
        """
        Initialize StorageMonitorService.
        
        Args:
            settings: Application configuration
            storage_checker: Utility for checking storage health
            websocket_manager: WebSocket manager for real-time updates
        """
        self._settings = settings
        self._storage_checker = storage_checker
        self._websocket_manager = websocket_manager
        
        # Runtime state
        self._is_running = False
        self._monitor_task: Optional[asyncio.Task] = None
        
        # Current storage state cache
        self._source_info: Optional[StorageInfo] = None
        self._destination_info: Optional[StorageInfo] = None
        
        self._logger = get_app_logger()
        self._logger.info("StorageMonitorService initialized with clean architecture")
    
    async def start_monitoring(self) -> None:
        """Start background monitoring with immediate first check."""
        if self._is_running:
            self._logger.warning("Storage monitoring already running")
            return
            
        self._is_running = True
        self._monitor_task = asyncio.create_task(self._monitoring_loop())
        self._logger.info("Storage monitoring started")
        
        # Immediate first check
        await self._check_all_storage()
    
    async def stop_monitoring(self) -> None:
        """Stop background monitoring gracefully."""
        if not self._is_running:
            return
            
        self._is_running = False
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        
        self._logger.info("Storage monitoring stopped")
    
    async def _monitoring_loop(self) -> None:
        """Main monitoring loop - runs on configured interval."""
        try:
            while self._is_running:
                try:
                    await self._check_all_storage()
                except Exception as e:
                    self._logger.error(f"Error in storage monitoring loop: {e}")
                
                # Wait for next check interval
                await asyncio.sleep(self._settings.storage_check_interval_seconds)
                
        except asyncio.CancelledError:
            self._logger.debug("Storage monitoring loop cancelled")
        except Exception as e:
            self._logger.error(f"Unexpected error in monitoring loop: {e}")
    
    async def _check_all_storage(self) -> None:
        """Check both source and destination storage using StorageChecker."""
        # Check source storage
        await self._check_single_storage(
            storage_type="source",
            path=self._settings.source_directory,
            warning_threshold=self._settings.source_warning_threshold_gb,
            critical_threshold=self._settings.source_critical_threshold_gb,
            current_info=self._source_info
        )
        
        # Check destination storage
        await self._check_single_storage(
            storage_type="destination", 
            path=self._settings.destination_directory,
            warning_threshold=self._settings.destination_warning_threshold_gb,
            critical_threshold=self._settings.destination_critical_threshold_gb,
            current_info=self._destination_info
        )
    
    async def _check_single_storage(self, storage_type: str, path: str,
                                   warning_threshold: float, critical_threshold: float,
                                   current_info: Optional[StorageInfo]) -> None:
        """
        Check single storage location and handle state updates.
        
        Args:
            storage_type: "source" or "destination"
            path: Path to check
            warning_threshold: Warning threshold in GB
            critical_threshold: Critical threshold in GB
            current_info: Current cached info for comparison
        """
        try:
            # Use StorageChecker for actual health check
            new_info = await self._storage_checker.check_path(
                path=path,
                warning_threshold_gb=warning_threshold,
                critical_threshold_gb=critical_threshold
            )
            
            # Update state cache
            if storage_type == "source":
                old_info = self._source_info
                self._source_info = new_info
            else:
                old_info = self._destination_info
                self._destination_info = new_info
            
            # Check for status changes and notify
            await self._handle_status_change(storage_type, old_info, new_info)
            
        except Exception as e:
            self._logger.error(f"Error checking {storage_type} storage at {path}: {e}")
    
    async def _handle_status_change(self, storage_type: str, 
                                   old_info: Optional[StorageInfo],
                                   new_info: StorageInfo) -> None:
        """
        Handle storage status changes and trigger notifications.
        
        Args:
            storage_type: "source" or "destination"
            old_info: Previous storage info (may be None)
            new_info: Current storage info
        """
        old_status = old_info.status if old_info else None
        new_status = new_info.status
        
        # Only notify on actual status changes
        if old_status != new_status:
            self._logger.info(
                f"{storage_type.title()} storage status changed: {old_status} -> {new_status}",
                extra={
                    "operation": "storage_status_change",
                    "storage_type": storage_type,
                    "old_status": old_status.value if old_status else None,
                    "new_status": new_status.value,
                    "free_space_gb": new_info.free_space_gb,
                    "path": new_info.path
                }
            )
            
            # Create storage update event
            update = StorageUpdate(
                storage_type=storage_type,
                old_status=old_status,
                new_status=new_status,
                storage_info=new_info
            )
            
            # Send to WebSocketManager if available
            await self._notify_websocket(update)
        else:
            # Log routine check results
            self._logger.debug(
                f"{storage_type.title()} storage: {new_status.value} "
                f"({new_info.free_space_gb:.1f}GB free)"
            )
    
    async def _notify_websocket(self, update: StorageUpdate) -> None:
        """
        Send storage update to WebSocketManager.
        
        Args:
            update: StorageUpdate event to broadcast
        """
        if not self._websocket_manager:
            return
            
        try:
            await self._websocket_manager.broadcast_storage_update(update)
        except Exception as e:
            self._logger.error(f"Error broadcasting storage update via WebSocket: {e}")
    
    async def trigger_immediate_check(self, storage_type: str = "destination") -> None:
        """
        Trigger immediate storage check for specified storage type.
        
        This can be called by other services (like FileCopyService) when they
        detect storage issues to provide instant WebSocket updates to UI.
        
        Args:
            storage_type: "source" or "destination" to check immediately
        """
        if not self._is_running:
            self._logger.warning(f"Storage monitoring not running - cannot trigger immediate {storage_type} check")
            return
            
        self._logger.debug(f"Triggering immediate {storage_type} check")
        
        try:
            if storage_type == "source":
                await self._check_single_storage(
                    storage_type="source",
                    path=self._settings.source_directory,
                    warning_threshold=self._settings.source_warning_threshold_gb,
                    critical_threshold=self._settings.source_critical_threshold_gb,
                    current_info=self._source_info
                )
            elif storage_type == "destination":
                await self._check_single_storage(
                    storage_type="destination", 
                    path=self._settings.destination_directory,
                    warning_threshold=self._settings.destination_warning_threshold_gb,
                    critical_threshold=self._settings.destination_critical_threshold_gb,
                    current_info=self._destination_info
                )
            else:
                self._logger.error(f"Invalid storage_type: {storage_type}")
                
        except Exception as e:
            self._logger.error(f"Error in immediate {storage_type} check: {e}")

    # API-friendly getter methods
    def get_source_info(self) -> Optional[StorageInfo]:
        """Get current source storage information."""
        return self._source_info
    
    def get_destination_info(self) -> Optional[StorageInfo]:
        """Get current destination storage information."""
        return self._destination_info
    
    def get_overall_status(self) -> StorageStatus:
        """
        Get overall system storage status.
        
        Returns the worst status between source and destination.
        Priority: CRITICAL > ERROR > WARNING > OK
        """
        statuses = []
        
        if self._source_info:
            statuses.append(self._source_info.status)
        if self._destination_info:
            statuses.append(self._destination_info.status)
        
        # No info available is ERROR
        if not statuses:
            return StorageStatus.ERROR
        
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
    
    def get_monitoring_status(self) -> dict:
        """
        Get monitoring service status for health checks.
        
        Returns:
            Dictionary with service status information
        """
        return {
            "is_running": self._is_running,
            "check_interval_seconds": self._settings.storage_check_interval_seconds,
            "source_monitored": self._source_info is not None,
            "destination_monitored": self._destination_info is not None,
            "overall_status": self.get_overall_status().value
        }