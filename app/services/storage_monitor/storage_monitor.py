"""
Storage Monitor Service for File Transfer Agent - Refactored for SRP Compliance.

Clean orchestrator service that manages storage monitoring for source and destination.
Uses StorageChecker for actual health checks and delegates to specialized components.
"""

import asyncio
from typing import Optional

from ..storage_checker import StorageChecker
from ...config import Settings
from ...logging_config import get_app_logger
from ...models import StorageInfo, StorageStatus

from .storage_state import StorageState
from .directory_manager import DirectoryManager
from .notification_handler import NotificationHandler


class StorageMonitorService:
    """
    Orchestrator for storage monitoring - SRP compliant version.
    
    Single Responsibility: Orchestration of storage monitoring ONLY
    Size: <200 lines (currently ~150 lines)
    
    Responsibilities:
    - Schedule periodic health checks using StorageChecker
    - Orchestrate specialized components (StorageState, DirectoryManager, NotificationHandler)
    - Provide API-friendly data access methods
    
    Clean Architecture:
    - Uses StorageChecker for actual checking logic
    - Delegates state management to StorageState
    - Delegates directory operations to DirectoryManager
    - Delegates notifications to NotificationHandler
    - Independent of outer layers (FastAPI, WebSockets)
    
    This class is responsible solely for orchestrating storage monitoring, adhering to SRP.
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
        # This class is responsible solely for orchestrating storage monitoring, adhering to SRP
        self._settings = settings
        self._storage_checker = storage_checker
        
        # Specialized components (SRP compliance)
        self._storage_state = StorageState()
        self._directory_manager = DirectoryManager()
        self._notification_handler = NotificationHandler(websocket_manager)
        
        # Runtime state (minimal, orchestration only)
        self._is_running = False
        self._monitor_task: Optional[asyncio.Task] = None
        
        self._logger = get_app_logger()
        self._logger.info("StorageMonitorService initialized with SRP-compliant architecture")
    
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
            critical_threshold=self._settings.source_critical_threshold_gb
        )
        
        # Check destination storage
        await self._check_single_storage(
            storage_type="destination", 
            path=self._settings.destination_directory,
            warning_threshold=self._settings.destination_warning_threshold_gb,
            critical_threshold=self._settings.destination_critical_threshold_gb
        )
    
    async def _check_single_storage(self, storage_type: str, path: str,
                                   warning_threshold: float, critical_threshold: float) -> None:
        """
        Check single storage location and handle state updates.
        Enhanced with directory recreation capability for runtime resilience.
        
        Args:
            storage_type: "source" or "destination"
            path: Path to check
            warning_threshold: Warning threshold in GB
            critical_threshold: Critical threshold in GB
        """
        try:
            # Use StorageChecker for actual health check
            new_info = await self._storage_checker.check_path(
                path=path,
                warning_threshold_gb=warning_threshold,
                critical_threshold_gb=critical_threshold
            )
            
            # Enhanced: If directory is not accessible, attempt recreation
            if not new_info.is_accessible:
                self._logger.warning(f"{storage_type.title()} directory not accessible: {path}. Attempting recreation.")
                recreation_success = await self._directory_manager.ensure_directory_exists(path, storage_type)
                
                if recreation_success:
                    # Re-check storage after successful recreation
                    self._logger.info(f"Re-checking {storage_type} storage after directory recreation")
                    new_info = await self._storage_checker.check_path(
                        path=path,
                        warning_threshold_gb=warning_threshold,
                        critical_threshold_gb=critical_threshold
                    )
            
            # Update state using StorageState component
            old_info = self._get_current_info(storage_type)
            self._update_storage_info(storage_type, new_info)
            
            # Handle status changes via NotificationHandler
            await self._notification_handler.handle_status_change(storage_type, old_info, new_info)
            
        except Exception as e:
            self._logger.error(f"Error checking {storage_type} storage at {path}: {e}")
    
    def _get_current_info(self, storage_type: str) -> Optional[StorageInfo]:
        """Get current storage info for comparison."""
        if storage_type == "source":
            return self._storage_state.get_source_info()
        else:
            return self._storage_state.get_destination_info()
    
    def _update_storage_info(self, storage_type: str, info: StorageInfo) -> None:
        """Update storage info via StorageState."""
        if storage_type == "source":
            self._storage_state.update_source_info(info)
        else:
            self._storage_state.update_destination_info(info)
    
    async def trigger_immediate_check(self, storage_type: str = "destination") -> None:
        """
        Trigger immediate storage check for specified storage type.
        
        This can be called by other services when they detect storage issues.
        
        Args:
            storage_type: "source" or "destination" to check immediately
        """
        if not self._is_running:
            self._logger.warning(f"Storage monitoring not running - cannot trigger immediate {storage_type} check")
            return
            
        self._logger.debug(f"Triggering immediate {storage_type} check")
        
        if storage_type == "source":
            await self._check_single_storage(
                storage_type="source",
                path=self._settings.source_directory,
                warning_threshold=self._settings.source_warning_threshold_gb,
                critical_threshold=self._settings.source_critical_threshold_gb
            )
        else:
            await self._check_single_storage(
                storage_type="destination",
                path=self._settings.destination_directory,
                warning_threshold=self._settings.destination_warning_threshold_gb,
                critical_threshold=self._settings.destination_critical_threshold_gb
            )
    
    # Delegated methods to StorageState (API compatibility)
    def get_source_info(self) -> Optional[StorageInfo]:
        """Get current source storage info."""
        return self._storage_state.get_source_info()
    
    def get_destination_info(self) -> Optional[StorageInfo]:
        """Get current destination storage info."""
        return self._storage_state.get_destination_info()
    
    def get_overall_status(self) -> StorageStatus:
        """Get overall storage status."""
        return self._storage_state.get_overall_status()
    
    def get_directory_readiness(self) -> dict:
        """Get current directory readiness state."""
        return self._storage_state.get_directory_readiness()
    
    def get_monitoring_status(self) -> dict:
        """Get monitoring service status for health checks."""
        status = self._storage_state.get_monitoring_status()
        status.update({
            "is_running": self._is_running,
            "check_interval_seconds": self._settings.storage_check_interval_seconds
        })
        return status