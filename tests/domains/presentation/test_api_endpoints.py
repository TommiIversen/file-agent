"""Tests for get_initial_state endpoint — presentation/api_endpoints.py."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.domains.presentation.api_endpoints import get_initial_state


def _tracked_file(file_path="/src/test.mxf", file_size=5_000_000):
    tf = MagicMock()
    tf.file_path = file_path
    tf.file_size = file_size
    tf.model_dump.return_value = {
        "id": "f1",
        "file_path": file_path,
        "file_size": file_size,
        "status": "discovered",
    }
    return tf


def _tally_status(is_online=True, is_monitoring=True, ip="192.168.1.100"):
    return {
        "is_online": is_online,
        "switch_type": "IP Power 9255",
        "ip_address": ip,
        "last_checked": "2026-01-01T00:00:00",
        "error_message": None,
        "is_monitoring": is_monitoring,
    }


class TestGetInitialState:
    async def test_returns_all_keys(self):
        query_bus = AsyncMock()
        files = [_tracked_file()]
        stats = {"total_files": 1}
        storage = {"free_gb": 100}
        query_bus.execute.side_effect = [files, stats, storage, _tally_status(), {"is_connected": True}]

        result = await get_initial_state(query_bus=query_bus)

        assert set(result.keys()) == {"files", "statistics", "storage", "scanner", "tally_switch", "ingest_connection"}

    async def test_files_serialized(self):
        query_bus = AsyncMock()
        tf = _tracked_file(file_size=2_097_152)  # 2 MB
        query_bus.execute.side_effect = [[tf], {"total_files": 1}, {}, _tally_status(), {"is_connected": True}]

        result = await get_initial_state(query_bus=query_bus)

        assert len(result["files"]) == 1
        assert result["files"][0]["file_size_mb"] == 2.0

    async def test_tally_service_none(self):
        """When tally query raises, fallback status is returned."""
        query_bus = AsyncMock()
        query_bus.execute.side_effect = [[], {"total_files": 0}, {}, Exception("no handler"), {"is_connected": False}]

        result = await get_initial_state(query_bus=query_bus)

        assert result["tally_switch"]["is_online"] is None
        assert result["tally_switch"]["is_monitoring"] is False

    async def test_tally_service_no_current_status(self):
        """When tally query raises, fallback status applies."""
        query_bus = AsyncMock()
        query_bus.execute.side_effect = [[], {"total_files": 0}, {}, Exception("no status"), {"is_connected": False}]

        result = await get_initial_state(query_bus=query_bus)

        assert result["tally_switch"]["is_online"] is None

    async def test_tally_service_raises_exception(self):
        """When tally query raises, error status is returned."""
        query_bus = AsyncMock()
        query_bus.execute.side_effect = [[], {"total_files": 0}, {}, RuntimeError("boom"), {"is_connected": False}]

        result = await get_initial_state(query_bus=query_bus)

        assert result["tally_switch"]["is_online"] is None
        assert "boom" in result["tally_switch"]["error_message"]

    async def test_ingest_worker_none(self):
        """When ingest query raises, fallback status applies."""
        query_bus = AsyncMock()
        query_bus.execute.side_effect = [[], {"total_files": 0}, {}, _tally_status(), Exception("no worker")]

        result = await get_initial_state(query_bus=query_bus)

        assert result["ingest_connection"]["is_connected"] is False

    async def test_ingest_worker_raises_exception(self):
        """When ingest query raises RuntimeError, fallback applies."""
        query_bus = AsyncMock()
        query_bus.execute.side_effect = [[], {"total_files": 0}, {}, _tally_status(), RuntimeError("no worker")]

        result = await get_initial_state(query_bus=query_bus)

        assert result["ingest_connection"]["is_connected"] is False

    async def test_tally_online_with_monitoring(self):
        """Full happy path — tally online and monitoring."""
        query_bus = AsyncMock()
        query_bus.execute.side_effect = [[], {"total_files": 0}, {}, _tally_status(is_online=True, is_monitoring=True), {"is_connected": True}]

        result = await get_initial_state(query_bus=query_bus)

        assert result["tally_switch"]["is_online"] is True
        assert result["tally_switch"]["is_monitoring"] is True
        assert result["ingest_connection"]["is_connected"] is True
