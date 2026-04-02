"""
Tests for WebSocketManager._broadcast_to_connections — covers all branches.
"""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock

from fastapi import WebSocketDisconnect

from app.domains.presentation.websocket_manager import WebSocketManager


@pytest.fixture
def manager():
    return WebSocketManager()


def _make_ws(*, fail: Exception | None = None) -> AsyncMock:
    ws = AsyncMock()
    if fail:
        ws.send_text.side_effect = fail
    return ws


class TestBroadcastToConnections:

    async def test_no_connections_does_nothing(self, manager):
        await manager._broadcast_to_connections({"type": "test"})
        # No error, no connections — just returns

    async def test_single_connection_receives_message(self, manager):
        ws = _make_ws()
        manager._connections.append(ws)

        await manager._broadcast_to_connections({"type": "hello", "data": 42})

        ws.send_text.assert_awaited_once()
        sent = json.loads(ws.send_text.call_args[0][0])
        assert sent["type"] == "hello"
        assert sent["data"] == 42

    async def test_multiple_connections_all_receive(self, manager):
        ws1 = _make_ws()
        ws2 = _make_ws()
        manager._connections.extend([ws1, ws2])

        await manager._broadcast_to_connections({"type": "broadcast"})

        ws1.send_text.assert_awaited_once()
        ws2.send_text.assert_awaited_once()

    async def test_disconnected_client_removed(self, manager):
        ws_good = _make_ws()
        ws_bad = _make_ws(fail=WebSocketDisconnect())
        manager._connections.extend([ws_good, ws_bad])

        await manager._broadcast_to_connections({"type": "test"})

        assert ws_good in manager._connections
        assert ws_bad not in manager._connections

    async def test_generic_error_removes_client(self, manager):
        ws_good = _make_ws()
        ws_bad = _make_ws(fail=ConnectionResetError("reset"))
        manager._connections.extend([ws_good, ws_bad])

        await manager._broadcast_to_connections({"type": "test"})

        assert ws_good in manager._connections
        assert ws_bad not in manager._connections

    async def test_multiple_failures_all_removed(self, manager):
        ws1 = _make_ws(fail=WebSocketDisconnect())
        ws2 = _make_ws(fail=OSError("broken pipe"))
        ws_ok = _make_ws()
        manager._connections.extend([ws1, ws2, ws_ok])

        await manager._broadcast_to_connections({"type": "test"})

        assert len(manager._connections) == 1
        assert ws_ok in manager._connections
