import logging
from typing import Optional

from app.core.events.event_bus import DomainEventBus
from app.core.events.storage_events import (
    MountStatusChangedEvent, 
    StorageStatusChangedEvent,
    DestinationUnavailableEvent,
    DestinationRecoveredEvent
)

from app.models import StorageInfo, StorageUpdate, MountStatusUpdate


class NotificationHandler:
    def __init__(self, event_bus: DomainEventBus):
        self._event_bus = event_bus
        self._last_mount_status = {}  # Track last known mount status per storage

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
        # Check if this is actually a status change
        storage_key = f"{mount_update.storage_type}_{mount_update.share_url}"
        last_status = self._last_mount_status.get(storage_key)
        current_status = mount_update.mount_status
        
        # Only log and publish event if status actually changed
        if last_status != current_status:
            logging.info(
                f"Mount status update: {mount_update.storage_type} -> {current_status.value}",
                extra={
                    "operation": "mount_status_update",
                    "storage_type": mount_update.storage_type,
                    "mount_status": current_status.value,
                    "share_url": mount_update.share_url,
                    "target_path": mount_update.target_path,
                    "error_message": mount_update.error_message,
                },
            )
            
            try:
                await self._event_bus.publish(MountStatusChangedEvent(update=mount_update))
            except Exception as e:
                logging.error(f"Error publishing MountStatusChangedEvent: {e}")
        else:
            # Just debug log for unchanged status
            logging.debug(
                f"Mount status unchanged: {mount_update.storage_type} -> {current_status.value}"
            )
        
        # Update last known status
        self._last_mount_status[storage_key] = current_status

    async def publish_destination_unavailable(
        self, reason: str, storage_info: StorageInfo
    ) -> None:
        """Publish domain event when destination becomes unavailable."""
        try:
            await self._event_bus.publish(
                DestinationUnavailableEvent(reason=reason, storage_info=storage_info)
            )
            logging.debug(f"Published DestinationUnavailableEvent: {reason}")
        except Exception as e:
            logging.error(f"Error publishing DestinationUnavailableEvent: {e}")

    async def publish_destination_recovered(
        self, reason: str, storage_info: StorageInfo
    ) -> None:
        """Publish domain event when destination recovers."""
        try:
            await self._event_bus.publish(
                DestinationRecoveredEvent(reason=reason, storage_info=storage_info)
            )
            logging.debug(f"Published DestinationRecoveredEvent: {reason}")
        except Exception as e:
            logging.error(f"Error publishing DestinationRecoveredEvent: {e}")

