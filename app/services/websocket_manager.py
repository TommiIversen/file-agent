import asyncio
import json
import logging
from datetime import datetime
from typing import List, Dict, Any

from fastapi import WebSocket, WebSocketDisconnect

from app.core.events.event_bus import DomainEventBus
from app.core.events.file_events import FileStatusChangedEvent, FileCopyProgressEvent
from app.core.events.scanner_events import ScannerStatusChangedEvent
from app.core.events.storage_events import MountStatusChangedEvent, StorageStatusChangedEvent
from app.core.file_repository import FileRepository
from app.models import FileStatus, TrackedFile


def _serialize_storage_info(storage_info) -> dict:
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
    """
    Serialize TrackedFile using Pydantic's built-in JSON serialization.

    Uses mode='json' to automatically handle datetime objects and other types.
    """
    # Use mode='json' to automatically convert datetime and other objects to JSON-compatible types
    data = tracked_file.model_dump(mode="json")

    # Add computed field for UI convenience
    data["file_size_mb"] = round(tracked_file.file_size / (1024 * 1024), 2)

    return data


class WebSocketManager:
    def __init__(
        self,
        file_repository: FileRepository,
        event_bus: DomainEventBus = None,
        storage_monitor=None,
    ):
        self.file_repository = file_repository
        self._storage_monitor = storage_monitor
        self._event_bus = event_bus
        self._lock = asyncio.Lock()
        self._connections: List[WebSocket] = []
        self._scanner_status = {
            "scanning": True,
            "paused": False,
        }

        if self._event_bus:
            asyncio.create_task(self._subscribe_to_events())

        logging.info("WebSocketManager initialiseret")

    def _is_more_current(self, file1: TrackedFile, file2: TrackedFile) -> bool:
        active_statuses = {
            FileStatus.COPYING: 1,
            FileStatus.IN_QUEUE: 2,
            FileStatus.GROWING_COPY: 3,
            FileStatus.READY_TO_START_GROWING: 4,
            FileStatus.READY: 5,
            FileStatus.GROWING: 6,
            FileStatus.DISCOVERED: 7,
            FileStatus.WAITING_FOR_SPACE: 8,
            FileStatus.WAITING_FOR_NETWORK: 8,
            FileStatus.COMPLETED: 9,
            FileStatus.FAILED: 10,
            FileStatus.REMOVED: 11,
            FileStatus.SPACE_ERROR: 12,
        }
        priority1 = active_statuses.get(file1.status, 99)
        priority2 = active_statuses.get(file2.status, 99)
        if priority1 != priority2:
            return priority1 < priority2
        time1 = file1.discovered_at.timestamp() if file1.discovered_at else 0
        time2 = file2.discovered_at.timestamp() if file2.discovered_at else 0
        return time1 > time2

    async def get_statistics(self) -> Dict:
        async with self._lock:
            current_files = {}
            all_files = await self.file_repository.get_all()
            for tracked_file in all_files:
                current = current_files.get(tracked_file.file_path)
                if not current or self._is_more_current(tracked_file, current):
                    current_files[tracked_file.file_path] = tracked_file
            current_files_list = list(current_files.values())
            total_files = len(current_files_list)
            status_counts = {}
            for status in FileStatus:
                status_counts[status.value] = len(
                    [f for f in current_files_list if f.status == status]
                )
            total_size = sum(f.file_size for f in current_files_list)
            copying_files = [
                f for f in current_files_list if f.status == FileStatus.COPYING
            ]
            growing_files = [
                f
                for f in current_files_list
                if f.status
                in [
                    FileStatus.GROWING,
                    FileStatus.READY_TO_START_GROWING,
                    FileStatus.GROWING_COPY,
                ]
            ]
            return {
                "total_files": total_files,
                "status_counts": status_counts,
                "total_size_bytes": total_size,
                "active_copies": len(copying_files),
                "growing_files": len(growing_files),
            }

    async def _subscribe_to_events(self):
        await self._event_bus.subscribe(
            FileStatusChangedEvent, self.handle_file_status_changed_event
        )
        await self._event_bus.subscribe(
            FileCopyProgressEvent, self.handle_file_copy_progress
        )
        await self._event_bus.subscribe(
            StorageStatusChangedEvent, self.handle_storage_status_event
        )
        await self._event_bus.subscribe(
            MountStatusChangedEvent, self.handle_mount_status_event
        )
        await self._event_bus.subscribe(
            ScannerStatusChangedEvent, self.handle_scanner_status_event
        )

        logging.info("Subscribed to DomainEventBus for real-time event updates")

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)

        await self._send_initial_state(websocket)

        logging.info(
            f"WebSocket client connected. Total connections: {len(self._connections)}"
        )

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)

        logging.info(
            f"WebSocket client disconnected. Total connections: {len(self._connections)}"
        )

    async def _send_initial_state(self, websocket: WebSocket) -> None:
        try:
            all_files = await self.file_repository.get_all()
            statistics = await self.get_statistics()

            storage_data = None
            if self._storage_monitor:
                source_info = self._storage_monitor.get_source_info()
                destination_info = self._storage_monitor.get_destination_info()
                overall_status = self._storage_monitor.get_overall_status()

                storage_data = {
                    "source": _serialize_storage_info(source_info)
                    if source_info
                    else None,
                    "destination": _serialize_storage_info(destination_info)
                    if destination_info
                    else None,
                    "overall_status": overall_status.value,
                    "monitoring_active": self._storage_monitor.get_monitoring_status()[
                        "is_running"
                    ],
                }

            initial_data = {
                "type": "initial_state",
                "data": {
                    "files": [_serialize_tracked_file(f) for f in all_files],
                    "statistics": statistics,
                    "storage": storage_data,
                    "scanner": self._scanner_status,
                    "timestamp": self._get_timestamp(),
                },
            }

            await websocket.send_text(json.dumps(initial_data))
            logging.debug(
                f"Sent initial state to client: {len(all_files)} files, storage: {storage_data is not None}"
            )

        except Exception as e:
            logging.error(f"Fejl ved sending af initial state: {e}")


    async def handle_file_status_changed_event(
        self, update: FileStatusChangedEvent
    ) -> None:
        """Handles the FileStatusChangedEvent from the new event bus."""
        logging.info(f"Received event: {update.file_path} -> {update.new_status.value}")
        if not self._connections:
            return

        tracked_file = await self.file_repository.get_by_id(update.file_id)
        if not tracked_file:
            logging.warning(
                f"Received FileStatusChangedEvent for unknown file ID: {update.file_id}"
            )
            return

        try:
            message_data = {
                "type": "file_update",
                "data": {
                    "file_path": update.file_path,
                    "old_status": update.old_status.value
                    if update.old_status
                    else None,
                    "new_status": update.new_status.value,
                    "file": _serialize_tracked_file(tracked_file),
                    "timestamp": update.timestamp.isoformat(),
                },
            }

            await self._broadcast_message(message_data)

            logging.debug(
                f"Broadcasted state change (legacy): {update.file_path} -> {update.new_status}"
            )

        except Exception as e:
            logging.error(f"Fejl ved broadcasting af state change: {e}")


    async def handle_file_copy_progress(self, event: FileCopyProgressEvent) -> None:
        """Handles the FileCopyProgressEvent from the event bus."""
        if not self._connections:
            return

        try:
            progress_percent = (
                (event.bytes_copied / event.total_bytes) * 100
                if event.total_bytes > 0
                else 0
            )
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
            await self._broadcast_message(message_data)
        except Exception as e:
            logging.error(f"Error broadcasting progress update: {e}")

    async def _broadcast_message(self, message_data: Dict[str, Any]) -> None:
        if not self._connections:
            return

        message_json = json.dumps(message_data)
        disconnected_clients = []

        for websocket in self._connections:
            try:
                await websocket.send_text(message_json)

            except WebSocketDisconnect:
                disconnected_clients.append(websocket)
                logging.debug("Client disconnected during broadcast")

            except Exception as e:
                disconnected_clients.append(websocket)
                logging.warning(f"Fejl ved sending til client: {e}")

        for websocket in disconnected_clients:
            self.disconnect(websocket)

    def _get_timestamp(self) -> str:
        return datetime.now().isoformat()


    async def handle_scanner_status_event(self, event: ScannerStatusChangedEvent) -> None:
        if not self._connections:
            return

        self._scanner_status = {"scanning": event.is_scanning, "paused": event.is_paused}

        try:
            message_data = {
                "type": "scanner_status",
                "data": {
                    "scanning": event.is_scanning,
                    "paused": event.is_paused,
                    "timestamp": self._get_timestamp(),
                },
            }

            await self._broadcast_message(message_data)

            logging.debug(
                f"Broadcasted scanner status: scanning={event.is_scanning}, paused={event.is_paused}"
            )

        except Exception as e:
            logging.error(f"Error broadcasting scanner status: {e}")


    async def handle_storage_status_event(self, event: StorageStatusChangedEvent) -> None:
        if not self._connections:
            return

        try:

            update_data = event.update

            message_data = {
                "type": "storage_update",
                "data": {
                    "storage_type": update_data.storage_type,
                    "old_status": update_data.old_status.value
                    if update_data.old_status
                    else None,
                    "new_status": update_data.new_status.value,
                    "storage_info": _serialize_storage_info(update_data.storage_info),
                    "timestamp": self._get_timestamp(),
                },
            }

            await self._broadcast_message(message_data)

            logging.debug(
                f"Broadcasted storage update: {update_data.storage_type} -> {update_data.new_status.value}"
            )

        except Exception as e:
            logging.error(f"Error broadcasting storage update: {e}")


    async def handle_mount_status_event(self, update: MountStatusChangedEvent) -> None:
        if not self._connections:
            return

        try:
            message_data = {
                "type": "mount_status",
                "data": {
                    "storage_type": update.storage_type,
                    "mount_status": update.mount_status.value,
                    "share_url": update.share_url,
                    "mount_path": update.mount_path,
                    "target_path": update.target_path,
                    "error_message": update.error_message,
                    "timestamp": self._get_timestamp(),
                },
            }

            await self._broadcast_message(message_data)

            logging.debug(
                f"Broadcasted mount status: {update.storage_type} -> {update.mount_status.value}"
            )

        except Exception as e:
            logging.error(f"Error broadcasting mount status: {e}")
