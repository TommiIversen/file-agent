"""Tests for get_initial_state endpoint — presentation/api_endpoints.py."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

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


def _tally_service(is_online=True, is_monitoring=True, ip="192.168.1.100"):
    svc = MagicMock()
    svc.is_monitoring = is_monitoring
    svc._ip_address = ip
    status = MagicMock()
    status.is_online = is_online
    status.last_checked = MagicMock()
    status.last_checked.isoformat.return_value = "2026-01-01T00:00:00"
    status.error_message = None
    svc.current_status = status
    return svc


class TestGetInitialState:
    async def test_returns_all_keys(self):
        query_bus = AsyncMock()
        files = [_tracked_file()]
        stats = {"total_files": 1}
        storage = {"free_gb": 100}
        query_bus.execute.side_effect = [files, stats, storage]

        with (
            patch("app.domains.presentation.api_endpoints.get_tally_switch_monitor", return_value=_tally_service()),
            patch("app.domains.presentation.api_endpoints.get_ingest_monitor_worker", return_value=MagicMock(get_connection_status=MagicMock(return_value=True))),
        ):
            result = await get_initial_state(query_bus=query_bus)

        assert set(result.keys()) == {"files", "statistics", "storage", "scanner", "tally_switch", "ingest_connection"}

    async def test_files_serialized(self):
        query_bus = AsyncMock()
        tf = _tracked_file(file_size=2_097_152)  # 2 MB
        query_bus.execute.side_effect = [[tf], {"total_files": 1}, {}]

        with (
            patch("app.domains.presentation.api_endpoints.get_tally_switch_monitor", return_value=_tally_service()),
            patch("app.domains.presentation.api_endpoints.get_ingest_monitor_worker", return_value=MagicMock(get_connection_status=MagicMock(return_value=True))),
        ):
            result = await get_initial_state(query_bus=query_bus)

        assert len(result["files"]) == 1
        assert result["files"][0]["file_size_mb"] == 2.0

    async def test_tally_service_none(self):
        """When tally monitor returns None, fallback status is returned."""
        query_bus = AsyncMock()
        query_bus.execute.side_effect = [[], {"total_files": 0}, {}]

        with (
            patch("app.domains.presentation.api_endpoints.get_tally_switch_monitor", return_value=None),
            patch("app.domains.presentation.api_endpoints.get_ingest_monitor_worker", return_value=MagicMock(get_connection_status=MagicMock(return_value=False))),
        ):
            result = await get_initial_state(query_bus=query_bus)

        assert result["tally_switch"]["is_online"] is False
        assert result["tally_switch"]["is_monitoring"] is False

    async def test_tally_service_no_current_status(self):
        """When tally service exists but current_status is None."""
        svc = MagicMock()
        svc.current_status = None

        query_bus = AsyncMock()
        query_bus.execute.side_effect = [[], {"total_files": 0}, {}]

        with (
            patch("app.domains.presentation.api_endpoints.get_tally_switch_monitor", return_value=svc),
            patch("app.domains.presentation.api_endpoints.get_ingest_monitor_worker", return_value=MagicMock(get_connection_status=MagicMock(return_value=False))),
        ):
            result = await get_initial_state(query_bus=query_bus)

        assert result["tally_switch"]["is_online"] is False

    async def test_tally_service_raises_exception(self):
        """When tally service raises, error status is returned."""
        query_bus = AsyncMock()
        query_bus.execute.side_effect = [[], {"total_files": 0}, {}]

        with (
            patch("app.domains.presentation.api_endpoints.get_tally_switch_monitor", side_effect=RuntimeError("boom")),
            patch("app.domains.presentation.api_endpoints.get_ingest_monitor_worker", return_value=MagicMock(get_connection_status=MagicMock(return_value=False))),
        ):
            result = await get_initial_state(query_bus=query_bus)

        assert result["tally_switch"]["is_online"] is None
        assert "boom" in result["tally_switch"]["error_message"]

    async def test_ingest_worker_none(self):
        """When ingest worker is None."""
        query_bus = AsyncMock()
        query_bus.execute.side_effect = [[], {"total_files": 0}, {}]

        with (
            patch("app.domains.presentation.api_endpoints.get_tally_switch_monitor", return_value=_tally_service()),
            patch("app.domains.presentation.api_endpoints.get_ingest_monitor_worker", return_value=None),
        ):
            result = await get_initial_state(query_bus=query_bus)

        assert result["ingest_connection"]["is_connected"] is False

    async def test_ingest_worker_raises_exception(self):
        """When ingest worker getter raises."""
        query_bus = AsyncMock()
        query_bus.execute.side_effect = [[], {"total_files": 0}, {}]

        with (
            patch("app.domains.presentation.api_endpoints.get_tally_switch_monitor", return_value=_tally_service()),
            patch("app.domains.presentation.api_endpoints.get_ingest_monitor_worker", side_effect=RuntimeError("no worker")),
        ):
            result = await get_initial_state(query_bus=query_bus)

        assert result["ingest_connection"]["is_connected"] is False

    async def test_tally_online_with_monitoring(self):
        """Full happy path — tally online and monitoring."""
        query_bus = AsyncMock()
        query_bus.execute.side_effect = [[], {"total_files": 0}, {}]

        with (
            patch("app.domains.presentation.api_endpoints.get_tally_switch_monitor", return_value=_tally_service(is_online=True, is_monitoring=True)),
            patch("app.domains.presentation.api_endpoints.get_ingest_monitor_worker", return_value=MagicMock(get_connection_status=MagicMock(return_value=True))),
        ):
            result = await get_initial_state(query_bus=query_bus)

        assert result["tally_switch"]["is_online"] is True
        assert result["tally_switch"]["is_monitoring"] is True
        assert result["ingest_connection"]["is_connected"] is True
