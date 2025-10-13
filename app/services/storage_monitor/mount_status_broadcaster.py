"""
Mount Status Broadcaster for File Transfer Agent.

This class is responsible solely for network mount status broadcasting
and coordination, adhering to SRP.
"""

from typing import Optional
import logging

from ...models import MountStatus, MountStatusUpdate


class MountStatusBroadcaster:
    """
    Handles network mount status broadcasting and coordination.

    Single Responsibility: Mount status communication ONLY
    Size: <100 lines (currently ~60 lines)

    This class is responsible solely for mount status broadcasting, adhering to SRP.
    """

    def __init__(self, notification_handler=None):
        """
        Initialize mount status broadcaster.

        Args:
            notification_handler: Notification handler for WebSocket broadcasting
        """
        # This class is responsible solely for mount status broadcasting, adhering to SRP
        self._notification_handler = notification_handler

    async def broadcast_mount_attempt(
        self, storage_type: str, share_url: str, target_path: str
    ) -> None:
        """
        Broadcast mount attempt status.

        Args:
            storage_type: "source" or "destination"
            share_url: Network share URL being mounted
            target_path: Target storage path
        """
        await self._broadcast_status(
            storage_type=storage_type,
            mount_status=MountStatus.ATTEMPTING,
            share_url=share_url,
            target_path=target_path,
        )

    async def broadcast_mount_success(
        self,
        storage_type: str,
        share_url: str,
        target_path: str,
        mount_path: Optional[str] = None,
    ) -> None:
        """
        Broadcast mount success status.

        Args:
            storage_type: "source" or "destination"
            share_url: Network share URL that was mounted
            target_path: Target storage path
            mount_path: Local mount path (optional)
        """
        await self._broadcast_status(
            storage_type=storage_type,
            mount_status=MountStatus.SUCCESS,
            share_url=share_url,
            target_path=target_path,
            mount_path=mount_path,
        )

    async def broadcast_mount_failure(
        self,
        storage_type: str,
        share_url: str,
        target_path: str,
        error_message: str = "Network mount operation failed",
    ) -> None:
        """
        Broadcast mount failure status.

        Args:
            storage_type: "source" or "destination"
            share_url: Network share URL that failed to mount
            target_path: Target storage path
            error_message: Error description
        """
        await self._broadcast_status(
            storage_type=storage_type,
            mount_status=MountStatus.FAILED,
            share_url=share_url,
            target_path=target_path,
            error_message=error_message,
        )

    async def broadcast_not_configured(
        self, storage_type: str, target_path: str
    ) -> None:
        """
        Broadcast mount not configured status.

        Args:
            storage_type: "source" or "destination"
            target_path: Target storage path
        """
        await self._broadcast_status(
            storage_type=storage_type,
            mount_status=MountStatus.NOT_CONFIGURED,
            target_path=target_path,
            error_message="Network mount not configured in settings",
        )

    async def _broadcast_status(
        self,
        storage_type: str,
        mount_status: MountStatus,
        target_path: str,
        share_url: Optional[str] = None,
        mount_path: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """
        Internal method to broadcast mount status via notification handler.

        Args:
            storage_type: "source" or "destination"
            mount_status: Current mount operation status
            target_path: Storage path that triggered mount operation
            share_url: Network share URL (optional)
            mount_path: Local mount path (optional)
            error_message: Error message (optional)
        """
        if not self._notification_handler:
            return

        try:
            mount_update = MountStatusUpdate(
                storage_type=storage_type,
                mount_status=mount_status,
                share_url=share_url,
                mount_path=mount_path,
                target_path=target_path,
                error_message=error_message,
            )

            await self._notification_handler.handle_mount_status(mount_update)

        except Exception as e:
            logging.error(f"Error broadcasting mount status: {e}")
