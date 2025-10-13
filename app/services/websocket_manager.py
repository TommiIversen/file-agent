"""
WebSocket Manager for File Transfer Agent.

WebSocketManager håndterer real-time updates til web UI via WebSockets.
Implementerer pub/sub pattern for at broadcaste StateManager changes
til alle forbundne klienter i real-time.

Følger roadmap Fase 6 specifikation.
"""

import json
import logging
from typing import List, Dict, Any
from fastapi import WebSocket, WebSocketDisconnect

from app.models import FileStateUpdate, StorageUpdate, MountStatusUpdate
from app.services.state_manager import StateManager


class WebSocketManager:
    """
    WebSocket connection manager for real-time UI updates.

    Ansvar:
    1. Connection Management: Håndter aktive WebSocket forbindelser
    2. State Broadcasting: Send real-time updates til alle klienter
    3. Event Subscription: Lyt på StateManager changes via pub/sub
    4. Message Formatting: Format data til JSON for frontend
    """

    def __init__(self, state_manager: StateManager, storage_monitor=None):
        """
        Initialize WebSocketManager.

        Args:
            state_manager: Central state manager to subscribe to
            storage_monitor: Storage monitor for getting storage data in initial state
        """
        self.state_manager = state_manager
        self._storage_monitor = storage_monitor
        self._connections: List[WebSocket] = []

        # Subscribe to StateManager events
        self.state_manager.subscribe(self._handle_state_change)

        logging.info("WebSocketManager initialiseret")
        logging.info("Subscribed til StateManager events for real-time updates")

    async def connect(self, websocket: WebSocket) -> None:
        """
        Accept new WebSocket connection og send initial data.

        Args:
            websocket: WebSocket connection to accept
        """
        await websocket.accept()
        self._connections.append(websocket)

        # Send initial state dump
        await self._send_initial_state(websocket)

        logging.info(
            f"WebSocket client connected. Total connections: {len(self._connections)}"
        )

    def disconnect(self, websocket: WebSocket) -> None:
        """
        Remove WebSocket connection from active list.

        Args:
            websocket: WebSocket connection to remove
        """
        if websocket in self._connections:
            self._connections.remove(websocket)

        logging.info(
            f"WebSocket client disconnected. Total connections: {len(self._connections)}"
        )

    async def _send_initial_state(self, websocket: WebSocket) -> None:
        """
        Send complete current state to newly connected client.

        Args:
            websocket: WebSocket to send initial state to
        """
        try:
            # Get current system state
            all_files = await self.state_manager.get_all_files()
            statistics = await self.state_manager.get_statistics()

            # Get storage data if available
            storage_data = None
            if self._storage_monitor:
                source_info = self._storage_monitor.get_source_info()
                destination_info = self._storage_monitor.get_destination_info()
                overall_status = self._storage_monitor.get_overall_status()

                storage_data = {
                    "source": self._serialize_storage_info(source_info)
                    if source_info
                    else None,
                    "destination": self._serialize_storage_info(destination_info)
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
                    "files": [self._serialize_tracked_file(f) for f in all_files],
                    "statistics": statistics,
                    "storage": storage_data,
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
        """
        Handle StateManager events og broadcast til alle klienter.

        Args:
            update: FileStateUpdate event fra StateManager
        """
        if not self._connections:
            return  # Ingen forbundne klienter

        try:
            # Format update til WebSocket message
            message_data = {
                "type": "file_update",
                "data": {
                    "file_path": update.file_path,
                    "old_status": update.old_status.value
                    if update.old_status
                    else None,
                    "new_status": update.new_status.value,
                    "file": self._serialize_tracked_file(update.tracked_file),
                    "timestamp": update.timestamp.isoformat(),
                },
            }

            # Broadcast til alle klienter
            await self._broadcast_message(message_data)

            logging.debug(
                f"Broadcasted state change: {update.file_path} -> {update.new_status}"
            )

        except Exception as e:
            logging.error(f"Fejl ved broadcasting af state change: {e}")

    async def _broadcast_message(self, message_data: Dict[str, Any]) -> None:
        """
        Broadcast message til alle aktive WebSocket forbindelser.

        Args:
            message_data: Data dictionary to send as JSON
        """
        if not self._connections:
            return

        message_json = json.dumps(message_data)
        disconnected_clients = []

        # Send til alle klienter
        for websocket in self._connections:
            try:
                await websocket.send_text(message_json)

            except WebSocketDisconnect:
                disconnected_clients.append(websocket)
                logging.debug("Client disconnected during broadcast")

            except Exception as e:
                disconnected_clients.append(websocket)
                logging.warning(f"Fejl ved sending til client: {e}")

        # Fjern disconnected klienter
        for websocket in disconnected_clients:
            self.disconnect(websocket)

    def _serialize_tracked_file(self, tracked_file) -> Dict[str, Any]:
        """
        Serialize TrackedFile til dictionary for JSON.

        Args:
            tracked_file: TrackedFile objekt

        Returns:
            Dictionary representation af filen
        """
        return {
            "file_path": tracked_file.file_path,
            "status": tracked_file.status.value,
            "file_size": tracked_file.file_size,
            "file_size_mb": round(tracked_file.file_size / (1024 * 1024), 2),
            "last_write_time": tracked_file.last_write_time.isoformat()
            if tracked_file.last_write_time
            else None,
            "copy_progress": tracked_file.copy_progress,
            "error_message": tracked_file.error_message,
            "retry_count": tracked_file.retry_count,
            "discovered_at": tracked_file.discovered_at.isoformat(),
            "started_copying_at": tracked_file.started_copying_at.isoformat()
            if tracked_file.started_copying_at
            else None,
            "completed_at": tracked_file.completed_at.isoformat()
            if tracked_file.completed_at
            else None,
            "destination_path": tracked_file.destination_path,
            # Growing file data
            "is_growing_file": tracked_file.is_growing_file,
            "growth_rate_mbps": tracked_file.growth_rate_mbps,
            "bytes_copied": tracked_file.bytes_copied,
            "copy_speed_mbps": tracked_file.copy_speed_mbps,
            "last_growth_check": tracked_file.last_growth_check.isoformat()
            if tracked_file.last_growth_check
            else None,
        }

    def _get_timestamp(self) -> str:
        """
        Get current timestamp as ISO string.

        Returns:
            Current timestamp in ISO format
        """
        from datetime import datetime

        return datetime.now().isoformat()

    async def send_system_statistics(self) -> None:
        """
        Send system statistics update til alle klienter.

        Bruges til periodiske system status updates.
        """
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
        """
        Broadcast storage status update til alle klienter.

        Args:
            update: StorageUpdate event fra StorageMonitorService
        """
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
                    "storage_info": self._serialize_storage_info(update.storage_info),
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
        """
        Broadcast network mount status update til alle klienter.

        Args:
            update: MountStatusUpdate event fra StorageMonitorService
        """
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

    def _serialize_storage_info(self, storage_info) -> dict:
        """
        Serialize StorageInfo til dictionary for JSON.

        Args:
            storage_info: StorageInfo objekt

        Returns:
            Dictionary representation af storage info
        """
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

    def get_connection_count(self) -> int:
        """
        Get antal aktive WebSocket forbindelser.

        Returns:
            Antal forbundne klienter
        """
        return len(self._connections)

    def get_manager_status(self) -> Dict[str, Any]:
        """
        Get WebSocketManager status information.

        Returns:
            Dictionary med manager status
        """
        return {
            "active_connections": len(self._connections),
            "subscribed_to_state_manager": True,
            "is_ready": True,
        }
