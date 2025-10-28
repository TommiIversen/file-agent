import json
import logging
from typing import List, Dict, Any

from fastapi import WebSocket, WebSocketDisconnect


class WebSocketManager:
    """Manages WebSocket connections and broadcasts messages."""

    def __init__(self):
        self._connections: List[WebSocket] = []
        logging.info("WebSocketManager initialiseret (Pure Connection Manager)")

    async def connect(self, websocket: WebSocket) -> None:
        """Accepts a new WebSocket connection."""
        await websocket.accept()
        self._connections.append(websocket)
        logging.info(f"WebSocket client connected. Total connections: {len(self._connections)}")

    def disconnect(self, websocket: WebSocket) -> None:
        """Removes a WebSocket connection."""
        if websocket in self._connections:
            self._connections.remove(websocket)
        logging.info(f"WebSocket client disconnected. Total connections: {len(self._connections)}")

    async def broadcast_message(self, message_data: Dict[str, Any]) -> None:
        """Broadcasts a JSON message to all connected clients."""
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