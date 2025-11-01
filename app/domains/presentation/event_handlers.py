import logging
from datetime import datetime
from typing import Dict, Any

from app.core.events.file_events import FileStatusChangedEvent, FileCopyProgressEvent
from app.core.events.scanner_events import ScannerStatusChangedEvent
from app.core.events.storage_events import MountStatusChangedEvent, StorageStatusChangedEvent
from app.core.file_repository import FileRepository
from app.domains.presentation.websocket_manager import WebSocketManager


def _serialize_storage_info(storage_info) -> dict:
    if not storage_info:
        return None
    return {
        "path": storage_info.path,
        "is_accessible": storage_info.is_accessible,
        "has_write_access": storage_info.has_write_access,
        "free_space_gb": round(storage_info.free_space_gb, 2),
        "total_space_gb": round(storage_info.total_space_gb, 2),
        "used_space_gb": round(storage_info.used_space_gb, 2),
        "status": storage_info.status.value,
        "warning_threshold_gb": storage_info.warning_threshold_gb,
        "critical_threshold_gb": storage_info.critical_threshold_gb,
        "last_checked": storage_info.last_checked.isoformat(),
        "error_message": storage_info.error_message,
    }


def _serialize_tracked_file(tracked_file) -> Dict[str, Any]:
    data = tracked_file.model_dump(mode="json")
    data["file_size_mb"] = round(tracked_file.file_size / (1024 * 1024), 2)
    return data


class PresentationEventHandlers:
    def __init__(self, websocket_manager: WebSocketManager, file_repository: FileRepository):
        self.websocket_manager = websocket_manager
        self.file_repository = file_repository
        self._scanner_status = {"scanning": True, "paused": False} # Initial state

    def _get_timestamp(self) -> str:
        return datetime.now().isoformat()

    async def handle_file_status_changed_event(self, update: FileStatusChangedEvent) -> None:
        logging.info(f"Received event: {update.file_path} -> {update.new_status.value}")
        tracked_file = await self.file_repository.get_by_id(update.file_id)
        if not tracked_file:
            logging.warning(f"Received FileStatusChangedEvent for unknown file ID: {update.file_id}")
            return

        message_data = {
            "type": "file_update",
            "data": {
                "file_path": update.file_path,
                "old_status": update.old_status.value if update.old_status else None,
                "new_status": update.new_status.value,
                "file": _serialize_tracked_file(tracked_file),
                "timestamp": update.timestamp.isoformat(),
            },
        }
        self.websocket_manager.broadcast_message(message_data)

    async def handle_file_copy_progress(self, event: FileCopyProgressEvent) -> None:
        progress_percent = (event.bytes_copied / event.total_bytes) * 100 if event.total_bytes > 0 else 0
        message_data = {
            "type": "file_progress_update",
            "data": {
                "file_id": event.file_id,
                "bytes_copied": event.bytes_copied,
                "total_bytes": event.total_bytes,
                "copy_speed_mbps": round(event.copy_speed_mbps, 2),
                "progress_percent": round(progress_percent, 2),
                "timestamp": event.timestamp.isoformat(),
            },
        }
        self.websocket_manager.broadcast_message(message_data)

    async def handle_scanner_status_event(self, event: ScannerStatusChangedEvent) -> None:
        self._scanner_status = {"scanning": event.is_scanning, "paused": event.is_paused}
        message_data = {
            "type": "scanner_status",
            "data": {
                "scanning": event.is_scanning,
                "paused": event.is_paused,
                "timestamp": self._get_timestamp(),
            },
        }
        self.websocket_manager.broadcast_message(message_data)

    async def handle_storage_status_event(self, event: StorageStatusChangedEvent) -> None:
        update_data = event.update
        message_data = {
            "type": "storage_update",
            "data": {
                "storage_type": update_data.storage_type,
                "old_status": update_data.old_status.value if update_data.old_status else None,
                "new_status": update_data.new_status.value,
                "storage_info": _serialize_storage_info(update_data.storage_info),
                "timestamp": self._get_timestamp(),
            },
        }
        self.websocket_manager.broadcast_message(message_data)

    async def handle_mount_status_event(self, event: MountStatusChangedEvent) -> None:
        update_data = event.update
        message_data = {
            "type": "mount_status",
            "data": {
                "storage_type": update_data.storage_type,
                "mount_status": update_data.mount_status.value,
                "share_url": update_data.share_url,
                "mount_path": update_data.mount_path,
                "target_path": update_data.target_path,
                "error_message": update_data.error_message,
                "timestamp": self._get_timestamp(),
            },
        }
        self.websocket_manager.broadcast_message(message_data)
