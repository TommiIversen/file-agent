"""
Tests for StorageQueryHandler — covers all branches for source and destination storage queries.
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from fastapi import HTTPException

from app.domains.shared.handlers.storage_query_handlers import StorageQueryHandler
from app.domains.shared.queries.storage_queries import (
    GetSourceStorageQuery,
    GetDestinationStorageQuery,
)
from app.models import StorageInfo, StorageStatus


def _make_storage_info(
    path: str = "/mnt/data",
    status: StorageStatus = StorageStatus.OK,
    free_space_gb: float = 100.0,
    error_message: str | None = None,
) -> StorageInfo:
    return StorageInfo(
        path=path,
        is_accessible=True,
        has_write_access=True,
        free_space_gb=free_space_gb,
        total_space_gb=500.0,
        used_space_gb=500.0 - free_space_gb,
        status=status,
        warning_threshold_gb=50.0,
        critical_threshold_gb=20.0,
        last_checked=datetime.now(),
        error_message=error_message,
    )


@pytest.fixture
def handler():
    return StorageQueryHandler()


@pytest.fixture
def mock_monitor():
    with patch(
        "app.domains.shared.handlers.storage_query_handlers.get_storage_monitor"
    ) as mock_get:
        monitor = MagicMock()
        mock_get.return_value = monitor
        yield monitor


# ── Source storage ───────────────────────────────────────────────────


class TestHandleGetSourceStorage:

    async def test_ok_returns_info(self, handler, mock_monitor):
        info = _make_storage_info(status=StorageStatus.OK)
        mock_monitor.get_source_info.return_value = info

        result = await handler.handle_get_source_storage(GetSourceStorageQuery())
        assert result == info

    async def test_none_raises_404(self, handler, mock_monitor):
        mock_monitor.get_source_info.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await handler.handle_get_source_storage(GetSourceStorageQuery())
        assert exc_info.value.status_code == 404

    async def test_critical_raises_503(self, handler, mock_monitor):
        info = _make_storage_info(status=StorageStatus.CRITICAL, error_message="disk dead")
        mock_monitor.get_source_info.return_value = info

        with pytest.raises(HTTPException) as exc_info:
            await handler.handle_get_source_storage(GetSourceStorageQuery())
        assert exc_info.value.status_code == 503
        assert "Critical" in exc_info.value.detail

    async def test_error_raises_503(self, handler, mock_monitor):
        info = _make_storage_info(status=StorageStatus.ERROR, error_message="not mounted")
        mock_monitor.get_source_info.return_value = info

        with pytest.raises(HTTPException) as exc_info:
            await handler.handle_get_source_storage(GetSourceStorageQuery())
        assert exc_info.value.status_code == 503
        assert "access error" in exc_info.value.detail

    async def test_warning_raises_507(self, handler, mock_monitor):
        info = _make_storage_info(status=StorageStatus.WARNING, free_space_gb=10.0)
        mock_monitor.get_source_info.return_value = info

        with pytest.raises(HTTPException) as exc_info:
            await handler.handle_get_source_storage(GetSourceStorageQuery())
        assert exc_info.value.status_code == 507
        assert "low on space" in exc_info.value.detail

    async def test_critical_without_error_message(self, handler, mock_monitor):
        info = _make_storage_info(status=StorageStatus.CRITICAL, error_message=None)
        mock_monitor.get_source_info.return_value = info

        with pytest.raises(HTTPException) as exc_info:
            await handler.handle_get_source_storage(GetSourceStorageQuery())
        assert "Unknown error" in exc_info.value.detail

    async def test_error_without_error_message(self, handler, mock_monitor):
        info = _make_storage_info(status=StorageStatus.ERROR, error_message=None)
        mock_monitor.get_source_info.return_value = info

        with pytest.raises(HTTPException) as exc_info:
            await handler.handle_get_source_storage(GetSourceStorageQuery())
        assert "not accessible" in exc_info.value.detail.lower() or "Path not accessible" in exc_info.value.detail


# ── Destination storage ──────────────────────────────────────────────


class TestHandleGetDestinationStorage:

    async def test_ok_returns_info(self, handler, mock_monitor):
        info = _make_storage_info(path="/mnt/dest", status=StorageStatus.OK)
        mock_monitor.get_destination_info.return_value = info

        result = await handler.handle_get_destination_storage(GetDestinationStorageQuery())
        assert result == info

    async def test_none_raises_404(self, handler, mock_monitor):
        mock_monitor.get_destination_info.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await handler.handle_get_destination_storage(GetDestinationStorageQuery())
        assert exc_info.value.status_code == 404

    async def test_critical_raises_503(self, handler, mock_monitor):
        info = _make_storage_info(status=StorageStatus.CRITICAL, error_message="disk dead")
        mock_monitor.get_destination_info.return_value = info

        with pytest.raises(HTTPException) as exc_info:
            await handler.handle_get_destination_storage(GetDestinationStorageQuery())
        assert exc_info.value.status_code == 503

    async def test_error_raises_503(self, handler, mock_monitor):
        info = _make_storage_info(status=StorageStatus.ERROR, error_message="unmounted")
        mock_monitor.get_destination_info.return_value = info

        with pytest.raises(HTTPException) as exc_info:
            await handler.handle_get_destination_storage(GetDestinationStorageQuery())
        assert exc_info.value.status_code == 503

    async def test_warning_raises_507(self, handler, mock_monitor):
        info = _make_storage_info(status=StorageStatus.WARNING, free_space_gb=5.0)
        mock_monitor.get_destination_info.return_value = info

        with pytest.raises(HTTPException) as exc_info:
            await handler.handle_get_destination_storage(GetDestinationStorageQuery())
        assert exc_info.value.status_code == 507
