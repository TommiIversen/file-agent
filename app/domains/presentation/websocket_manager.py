import asyncio
import json
import logging
from asyncio import Queue, Task
from typing import List, Dict, Any

from fastapi import WebSocket, WebSocketDisconnect


class WebSocketManager:
    """Manages WebSocket connections and broadcasts messages."""

    def __init__(self):
        self._connections: List[WebSocket] = []
        self._message_queue: Queue = Queue()
        self._sender_task: Task | None = None
        logging.info("WebSocketManager initialiseret (Pure Connection Manager)")

    def start_sender_task(self):
        """Starts the background task for sending messages."""
        if self._sender_task is None:
            self._sender_task = asyncio.create_task(self._message_sender_task())
            logging.info("WebSocket message sender task started.")

    def stop_sender_task(self):
        """Stops the background task for sending messages."""
        if self._sender_task:
            self._sender_task.cancel()
            self._sender_task = None
            logging.info("WebSocket message sender task stopped.")

    async def _message_sender_task(self):
        """The background task that sends messages from the queue."""
        while True:
            try:
                message_data = await self._message_queue.get()
                await self._broadcast_to_connections(message_data)
                self._message_queue.task_done()
            except asyncio.CancelledError:
                logging.info("Message sender task cancelled.")
                break
            except Exception as e:
                logging.error(f"Error in message sender task: {e}")

    async def _broadcast_to_connections(self, message_data: Dict[str, Any]):
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

    def broadcast_message(self, message_data: Dict[str, Any]) -> None:
        """Puts a message in the queue to be broadcast to all connected clients."""
        self._message_queue.put_nowait(message_data)