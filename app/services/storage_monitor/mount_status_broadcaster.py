import logging
from typing import Optional

from ...models import MountStatus, MountStatusUpdate


class MountStatusBroadcaster:
    def __init__(self, notification_handler=None):
        self._notification_handler = notification_handler

    async def broadcast_mount_attempt(
        self, storage_type: str, share_url: str, target_path: str
    ) -> None:
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
