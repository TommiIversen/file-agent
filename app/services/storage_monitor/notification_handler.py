"""
Notification Handler for File Transfer Agent.

This class is responsible solely for managing WebSocket notifications
and status change broadcasting, adhering to SRP.
"""

from typing import Optional
import logging

from ...models import StorageInfo, StorageUpdate, MountStatusUpdate



class NotificationHandler:
    """
    Manages WebSocket notifications and status change broadcasting.
    
    Single Responsibility: Notification handling ONLY
    Size: <100 lines (currently ~65 lines)
    
    This class is responsible solely for notification handling, adhering to SRP.
    """
    
    def __init__(self, websocket_manager=None):
        """
        Initialize notification handler.
        
        Args:
            websocket_manager: WebSocket manager for real-time updates
        """
        # This class is responsible solely for notification handling, adhering to SRP
        self._websocket_manager = websocket_manager
        
        
    async def handle_status_change(self, storage_type: str, 
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
            logging.info(
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
            logging.debug(
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
            logging.error(f"Error broadcasting storage update via WebSocket: {e}")
    
    async def handle_mount_status(self, mount_update: MountStatusUpdate) -> None:
        """
        Handle network mount status updates and trigger notifications.
        
        Args:
            mount_update: MountStatusUpdate event to broadcast
        """
        logging.info(
            f"Mount status update: {mount_update.storage_type} -> {mount_update.mount_status.value}",
            extra={
                "operation": "mount_status_update",
                "storage_type": mount_update.storage_type,
                "mount_status": mount_update.mount_status.value,
                "share_url": mount_update.share_url,
                "target_path": mount_update.target_path,
                "error_message": mount_update.error_message
            }
        )
        
        # Send to WebSocketManager if available
        await self._notify_mount_websocket(mount_update)
    
    async def _notify_mount_websocket(self, update: MountStatusUpdate) -> None:
        """
        Send mount status update to WebSocketManager.
        
        Args:
            update: MountStatusUpdate event to broadcast
        """
        if not self._websocket_manager:
            return
            
        try:
            await self._websocket_manager.broadcast_mount_status(update)
        except Exception as e:
            logging.error(f"Error broadcasting mount status via WebSocket: {e}")
