"""
Storage Monitor Service for File Transfer Agent - Refactored for SRP Compliance.

Clean orchestrator service that manages storage monitoring for source and destination.
Uses StorageChecker for actual health checks and delegates to specialized components.
"""

import asyncio
from typing import Optional
import logging
from ..storage_checker import StorageChecker
from ...config import Settings

from ...models import StorageInfo, StorageStatus

from .storage_state import StorageState
from .directory_manager import DirectoryManager
from .notification_handler import NotificationHandler
from .mount_status_broadcaster import MountStatusBroadcaster


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
                 websocket_manager=None, network_mount_service=None, job_queue=None):
        """
        Initialize StorageMonitorService.
        
        Args:
            settings: Application configuration
            storage_checker: Utility for checking storage health
            websocket_manager: WebSocket manager for real-time updates
            network_mount_service: Network mount service for automatic mounting
            job_queue: Job queue service for universal recovery (optional)
        """
        # This class is responsible solely for orchestrating storage monitoring, adhering to SRP
        self._settings = settings
        self._storage_checker = storage_checker
        self._network_mount_service = network_mount_service
        self._job_queue = job_queue  # For universal recovery system
        
        # Specialized components (SRP compliance)
        self._storage_state = StorageState()
        self._directory_manager = DirectoryManager()
        self._notification_handler = NotificationHandler(websocket_manager)
        self._mount_broadcaster = MountStatusBroadcaster(self._notification_handler)
        
        # Runtime state (minimal, orchestration only)
        self._is_running = False
        self._monitor_task: Optional[asyncio.Task] = None
        
        
        logging.info("StorageMonitorService initialized with SRP-compliant architecture")
    
    async def start_monitoring(self) -> None:
        """Start background monitoring with immediate first check."""
        if self._is_running:
            logging.warning("Storage monitoring already running")
            return
            
        self._is_running = True
        self._monitor_task = asyncio.create_task(self._monitoring_loop())
        logging.info("Storage monitoring started")
        
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
        
        logging.info("Storage monitoring stopped")
    
    async def _monitoring_loop(self) -> None:
        """Main monitoring loop - runs on configured interval."""
        try:
            while self._is_running:
                try:
                    await self._check_all_storage()
                except Exception as e:
                    logging.error(f"Error in storage monitoring loop: {e}")
                
                # Wait for next check interval
                await asyncio.sleep(self._settings.storage_check_interval_seconds)
                
        except asyncio.CancelledError:
            logging.debug("Storage monitoring loop cancelled")
        except Exception as e:
            logging.error(f"Unexpected error in monitoring loop: {e}")
    
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
            
            # Enhanced: If directory is not accessible, try network mount first (for destination), then directory recreation
            if not new_info.is_accessible:
                logging.warning(f"{storage_type.title()} directory not accessible: {path}.")
                
                # PHASE 2: Network mount integration - attempt network remount for destination paths
                mount_attempted = False
                if storage_type == "destination" and self._network_mount_service:
                    if self._network_mount_service.is_network_mount_configured():
                        share_url = self._network_mount_service.get_network_share_url()
                        if share_url:
                            logging.info(f"Attempting network mount for destination: {share_url}")
                            
                            # PHASE 3: Broadcast mount attempt status
                            await self._mount_broadcaster.broadcast_mount_attempt(
                                storage_type=storage_type,
                                share_url=share_url,
                                target_path=path
                            )
                            
                            mount_success = await self._network_mount_service.ensure_mount_available(share_url, path)
                            mount_attempted = True
                            
                            if mount_success:
                                logging.info(f"Network mount successful, re-checking storage: {path}")
                                
                                # PHASE 3: Broadcast mount success status
                                await self._mount_broadcaster.broadcast_mount_success(
                                    storage_type=storage_type,
                                    share_url=share_url,
                                    target_path=path
                                )
                                
                                # Re-check storage after successful mount
                                new_info = await self._storage_checker.check_path(
                                    path=path,
                                    warning_threshold_gb=warning_threshold,
                                    critical_threshold_gb=critical_threshold
                                )
                            else:
                                # PHASE 3: Broadcast mount failure status
                                await self._mount_broadcaster.broadcast_mount_failure(
                                    storage_type=storage_type,
                                    share_url=share_url,
                                    target_path=path
                                )
                    else:
                        # PHASE 3: Broadcast not configured status
                        await self._mount_broadcaster.broadcast_not_configured(
                            storage_type=storage_type,
                            target_path=path
                        )
                
                # Fallback: If still not accessible and no mount was attempted, try directory recreation
                if not new_info.is_accessible and not mount_attempted:
                    logging.info(f"Attempting directory recreation: {path}")
                    recreation_success = await self._directory_manager.ensure_directory_exists(path, storage_type)
                    
                    if recreation_success:
                        # Re-check storage after successful recreation
                        logging.info(f"Re-checking {storage_type} storage after directory recreation")
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
            
            # 🔄 INTELLIGENT PAUSE/RESUME: Handle destination state changes
            if self._is_destination_unavailable(storage_type, old_info, new_info):
                await self._handle_destination_unavailable(storage_type, old_info, new_info)
            elif self._is_destination_recovery(storage_type, old_info, new_info):
                await self._handle_destination_recovery(storage_type, old_info, new_info)
            
        except Exception as e:
            logging.error(f"Error checking {storage_type} storage at {path}: {e}")
    
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
            logging.warning(f"Storage monitoring not running - cannot trigger immediate {storage_type} check")
            return
            
        logging.debug(f"Triggering immediate {storage_type} check")
        
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
    
    def _is_destination_recovery(self, storage_type: str, old_info: Optional[StorageInfo], 
                                new_info: StorageInfo) -> bool:
        """
        Detect universal destination recovery scenarios.
        
        Recovery happens when destination transitions from problematic state to OK:
        - ERROR (network offline, mount failure) → OK  
        - CRITICAL (disk full, no write access) → OK
        
        Args:
            storage_type: Type of storage being checked
            old_info: Previous storage info (can be None on first check)
            new_info: Current storage info
            
        Returns:
            True if this is a destination recovery event
        """
        # Only handle destination recovery
        if storage_type != "destination":
            return False
            
        # No recovery if no previous state
        if not old_info:
            return False
            
        # Recovery = transition from problematic state to OK
        problematic_states = [StorageStatus.ERROR, StorageStatus.CRITICAL]
        is_recovery = (old_info.status in problematic_states and 
                      new_info.status == StorageStatus.OK)
        
        if is_recovery:
            logging.info(
                f"🔄 DESTINATION RECOVERY DETECTED: {old_info.status} → {new_info.status} "
                f"(path: {new_info.path})"
            )
        
        return is_recovery
    
    def _is_destination_unavailable(self, storage_type: str, old_info: Optional[StorageInfo], 
                                   new_info: StorageInfo) -> bool:
        """
        Detect destination unavailability scenarios.
        
        Unavailable happens when destination transitions from OK to problematic state:
        - OK → ERROR (network offline, mount failure)
        - OK → CRITICAL (disk full, no write access)
        
        Args:
            storage_type: Type of storage being checked
            old_info: Previous storage info (can be None on first check)
            new_info: Current storage info
            
        Returns:
            True if this is a destination unavailability event
        """
        # Only handle destination unavailability
        if storage_type != "destination":
            return False
            
        # No unavailability if no previous state
        if not old_info:
            return False
            
        # Unavailable = transition from OK to problematic state
        problematic_states = [StorageStatus.ERROR, StorageStatus.CRITICAL]
        is_unavailable = (old_info.status == StorageStatus.OK and 
                         new_info.status in problematic_states)
        
        if is_unavailable:
            logging.warning(
                f"⏸️ DESTINATION UNAVAILABLE: {old_info.status} → {new_info.status} "
                f"(path: {new_info.path})"
            )
        
        return is_unavailable
    
    async def _handle_destination_unavailable(self, storage_type: str, old_info: StorageInfo, 
                                            new_info: StorageInfo) -> None:
        """
        Handle destination unavailability by pausing active operations.
        
        Args:
            storage_type: Type of storage that became unavailable
            old_info: Previous storage state
            new_info: Current unavailable storage state
        """
        if not self._job_queue:
            logging.warning("⚠️ Job queue not available - cannot pause operations")
            return
            
        try:
            unavailable_reason = f"{old_info.status} → {new_info.status}"
            
            logging.warning(
                f"⏸️ PAUSING OPERATIONS: {unavailable_reason} "
                f"(Reason: {new_info.error_message or 'Unknown'})"
            )
            
            # Trigger intelligent pause via job queue
            await self._job_queue.handle_destination_unavailable()
            
            logging.info("⏸️ Operations paused successfully - awaiting recovery")
            
        except Exception as e:
            logging.error(f"❌ Error during destination pause handling: {e}")
    
    async def _handle_destination_recovery(self, storage_type: str, old_info: StorageInfo, 
                                         new_info: StorageInfo) -> None:
        """
        Handle destination recovery by triggering universal file recovery.
        
        Args:
            storage_type: Type of storage that recovered
            old_info: Previous storage state
            new_info: Current recovered storage state
        """
        if not self._job_queue:
            logging.warning("⚠️ Job queue not available - cannot perform automatic recovery")
            return
            
        try:
            recovery_reason = f"{old_info.status} → {new_info.status}"
            
            logging.info(
                f"🚀 INITIATING UNIVERSAL RECOVERY: {recovery_reason} "
                f"(Free space: {new_info.free_space_gb:.1f} GB)"
            )
            
            # Trigger intelligent resume via job queue
            await self._job_queue.handle_destination_recovery()
            
            logging.info("✅ Intelligent resume initiated successfully")
            
        except Exception as e:
            logging.error(f"❌ Error during universal recovery: {e}")
