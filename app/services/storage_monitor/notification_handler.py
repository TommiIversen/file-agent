import logging
from typing import Optional

from app.core.events.event_bus import DomainEventBus
from app.core.events.storage_events import MountStatusChangedEvent, StorageStatusChangedEvent

from ...models import StorageInfo, StorageUpdate, MountStatusUpdate


class NotificationHandler:
    def __init__(self, event_bus: DomainEventBus):
        self._event_bus = event_bus

    async def handle_status_change(
        self, storage_type: str, old_info: Optional[StorageInfo], new_info: StorageInfo
    ) -> None:
        old_status = old_info.status if old_info else None
        new_status = new_info.status

        # Always send websocket update - simple and reliable
        if old_status != new_status:
            logging.info(
                f"{storage_type.title()} storage status changed: {old_status} -> {new_status}",
                extra={
                    "operation": "storage_status_change",
                    "storage_type": storage_type,
                    "old_status": old_status.value if old_status else None,
                    "new_status": new_status.value,
                    "free_space_gb": new_info.free_space_gb,
                    "path": new_info.path,
                },
            )
        else:
            logging.debug(
                f"{storage_type.title()} storage: {new_status.value} "
                f"({new_info.free_space_gb:.1f}GB free)"
            )

        # Send websocket update every time - keep frontend in sync
        update = StorageUpdate(
            storage_type=storage_type,
            old_status=old_status,
            new_status=new_status,
            storage_info=new_info,
        )

        try:
            await self._event_bus.publish(StorageStatusChangedEvent(update=update))
        except Exception as e:
            logging.error(f"Error publishing StorageStatusChangedEvent: {e}")


    async def handle_mount_status(self, mount_update: MountStatusUpdate) -> None:
        logging.info(
            f"Mount status update: {mount_update.storage_type} -> {mount_update.mount_status.value}",
            extra={
                "operation": "mount_status_update",
                "storage_type": mount_update.storage_type,
                "mount_status": mount_update.mount_status.value,
                "share_url": mount_update.share_url,
                "target_path": mount_update.target_path,
                "error_message": mount_update.error_message,
            },
        )

        try:
            await self._event_bus.publish(MountStatusChangedEvent(update=mount_update))
        except Exception as e:
            logging.error(f"Error publishing MountStatusChangedEvent: {e}")

