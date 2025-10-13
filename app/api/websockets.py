from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from typing import Dict, Any

from app.services.websocket_manager import WebSocketManager
from app.dependencies import get_websocket_manager

router = APIRouter(prefix="/api/ws", tags=["websockets"])


@router.websocket("/live")
async def websocket_endpoint(
    websocket: WebSocket, ws_manager: WebSocketManager = Depends(get_websocket_manager)
):
    await ws_manager.connect(websocket)

    try:
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_text("pong")

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


@router.get("/status")
async def get_websocket_status(
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
) -> Dict[str, Any]:
    return ws_manager.get_manager_status()
