from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends

from app.dependencies import get_websocket_manager
from app.services.websocket_manager import WebSocketManager

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
