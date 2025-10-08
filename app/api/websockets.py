"""
WebSocket API endpoints for File Transfer Agent.

Implementerer WebSocket endpoint til real-time updates
og monitoring endpoints for WebSocket status.

Følger roadmap Fase 6 specifikation.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from typing import Dict, Any

from app.services.websocket_manager import WebSocketManager
from app.dependencies import get_websocket_manager

router = APIRouter(prefix="/api/ws", tags=["websockets"])


@router.websocket("/live")
async def websocket_endpoint(
    websocket: WebSocket,
    ws_manager: WebSocketManager = Depends(get_websocket_manager)
):
    """
    WebSocket endpoint for real-time updates.
    
    Connects clients and provides real-time file transfer updates.
    Initial state is sent immediately upon connection.
    """
    await ws_manager.connect(websocket)
    
    try:
        # Keep connection alive and handle any client messages
        while True:
            # Vent på messages fra client (kan være ping/pong etc.)
            message = await websocket.receive_text()
            
            # Simple heartbeat/ping response
            if message == "ping":
                await websocket.send_text("pong")
    
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


@router.get("/status")
async def get_websocket_status(
    ws_manager: WebSocketManager = Depends(get_websocket_manager)
) -> Dict[str, Any]:
    """
    Get WebSocket manager status.
    
    Returns:
        Dictionary med WebSocket manager status
    """
    return ws_manager.get_manager_status()