import asyncio
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from fastapi import WebSocket, WebSocketDisconnect

from app.core.events.event_bus import DomainEventBus
from app.core.events.file_events import FileStatusChangedEvent
from app.models import FileStateUpdate, StorageUpdate, MountStatusUpdate
from app.services.state_manager import StateManager


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
        state_manager: StateManager,
        event_bus: DomainEventBus = None,
        storage_monitor=None,
    ):
        self.state_manager = state_manager
        self._storage_monitor = storage_monitor
        self._event_bus = event_bus
        self._connections: List[WebSocket] = []
        self._scanner_status = {"scanning": True, "paused": False}  # Track scanner status

        # New system: Subscribe to the event bus
        if self._event_bus:
            asyncio.create_task(
                self._event_bus.subscribe(
                    FileStatusChangedEvent, self.handle_file_status_changed_event
                )
            )
            logging.info("Subscribed to DomainEventBus for real-time event updates")

        logging.info("WebSocketManager initialiseret")

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
            all_files = await self.state_manager.get_all_files()
            statistics = await self.state_manager.get_statistics()

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

    async def _handle_state_change(self, update: FileStateUpdate) -> None:
        """Handles the legacy FileStateUpdate from the old pub/sub system."""
        if not self._connections:
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
                    "file": _serialize_tracked_file(update.tracked_file),
                    "timestamp": update.timestamp.isoformat(),
                },
            }

            await self._broadcast_message(message_data)

            logging.debug(
                f"Broadcasted state change (legacy): {update.file_path} -> {update.new_status}"
            )

        except Exception as e:
            logging.error(f"Fejl ved broadcasting af state change: {e}")

    async def handle_file_status_changed_event(self, event: FileStatusChangedEvent) -> None:
        """Handles the FileStatusChangedEvent from the new event bus."""
        logging.info(f"Received event: {event.file_path} -> {event.new_status.value}")
        if not self._connections:
            return

        tracked_file = await self.state_manager.get_file_by_id(event.file_id)
        if not tracked_file:
            logging.warning(
                f"Received FileStatusChangedEvent for unknown file ID: {event.file_id}"
            )
            return

        update_for_broadcast = FileStateUpdate(
            file_path=event.file_path,
            old_status=event.old_status,
            new_status=event.new_status,
            tracked_file=tracked_file,
            timestamp=event.timestamp,  # Use event timestamp
        )
        # Re-use the existing broadcast logic by calling the old handler
        await self._handle_state_change(update_for_broadcast)

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

    async def send_system_statistics(self) -> None:
        if not self._connections:
            return

        try:
            statistics = await self.state_manager.get_statistics()

            message_data = {
                "type": "statistics_update",
                "data": {"statistics": statistics, "timestamp": self._get_timestamp()},
            }

            await self._broadcast_message(message_data)

        except Exception as e:
            logging.error(f"Fejl ved sending af statistics: {e}")

    async def broadcast_storage_update(self, update: StorageUpdate) -> None:
        if not self._connections:
            return

        try:
            message_data = {
                "type": "storage_update",
                "data": {
                    "storage_type": update.storage_type,
                    "old_status": update.old_status.value
                    if update.old_status
                    else None,
                    "new_status": update.new_status.value,
                    "storage_info": _serialize_storage_info(update.storage_info),
                    "timestamp": self._get_timestamp(),
                },
            }

            await self._broadcast_message(message_data)

            logging.debug(
                f"Broadcasted storage update: {update.storage_type} -> {update.new_status.value}"
            )

        except Exception as e:
            logging.error(f"Error broadcasting storage update: {e}")

    async def broadcast_mount_status(self, update: MountStatusUpdate) -> None:
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

    async def broadcast_scanner_status(self, scanning: bool, paused: bool) -> None:
        """Broadcast scanner status changes to all connected clients"""
        if not self._connections:
            return

        self._scanner_status = {"scanning": scanning, "paused": paused}

        try:
            message_data = {
                "type": "scanner_status",
                "data": {
                    "scanning": scanning,
                    "paused": paused,
                    "timestamp": self._get_timestamp(),
                },
            }

            await self._broadcast_message(message_data)

            logging.debug(f"Broadcasted scanner status: scanning={scanning}, paused={paused}")

        except Exception as e:
            logging.error(f"Error broadcasting scanner status: {e}")

    def initialize_scanner_status(self, file_scanner_service) -> None:
        """Initialize scanner status from file scanner service after startup"""
        try:
            # Check if scanner is running, but handle race condition gracefully
            is_scanning = file_scanner_service.is_scanning()
            
            # If scanner task was just created, it might not be running yet
            # In that case, assume it will be running soon (optimistic initialization)
            if not is_scanning:
                # Check if we have a background task that should be starting the scanner
                logging.debug("Scanner not yet running at initialization - will update when it starts")
                is_scanning = True  # Assume scanner will start successfully
                
            self._scanner_status = {"scanning": is_scanning, "paused": not is_scanning}
            logging.info(f"Scanner status initialized: scanning={is_scanning}, paused={not is_scanning}")
        except Exception as e:
            logging.error(f"Failed to initialize scanner status: {e}")
            self._scanner_status = {"scanning": False, "paused": True}
