"""
Tests for GetStatisticsQueryHandler — covers statistics calculation with various file states.
"""
import pytest
from unittest.mock import AsyncMock
from datetime import datetime

from app.domains.presentation.query_handlers import GetStatisticsQueryHandler
from app.domains.presentation.queries import GetStatisticsQuery
from app.models import TrackedFile, FileStatus


def _make_file(
    file_path: str = "/test/file.mxf",
    status: FileStatus = FileStatus.DISCOVERED,
    file_size: int = 1024,
    discovered_at: datetime | None = None,
) -> TrackedFile:
    return TrackedFile(
        file_path=file_path,
        status=status,
        file_size=file_size,
        discovered_at=discovered_at or datetime.now(),
    )


@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    repo.get_all = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def handler(mock_repo):
    return GetStatisticsQueryHandler(mock_repo)


class TestGetStatisticsQueryHandler:

    async def test_empty_repository(self, handler):
        result = await handler.handle(GetStatisticsQuery())
        assert result["total_files"] == 0
        assert result["totalFiles"] == 0
        assert result["activeFiles"] == 0
        assert result["completedFiles"] == 0
        assert result["failedFiles"] == 0
        assert result["growingFiles"] == 0
        assert result["total_size_bytes"] == 0

    async def test_single_discovered_file(self, handler, mock_repo):
        mock_repo.get_all.return_value = [_make_file(status=FileStatus.DISCOVERED)]
        result = await handler.handle(GetStatisticsQuery())
        assert result["total_files"] == 1
        assert result["activeFiles"] == 1
        assert result["completedFiles"] == 0

    async def test_completed_files_counted(self, handler, mock_repo):
        mock_repo.get_all.return_value = [
            _make_file(file_path="/a.mxf", status=FileStatus.COMPLETED),
            _make_file(file_path="/b.mxf", status=FileStatus.COMPLETED_DELETE_FAILED),
        ]
        result = await handler.handle(GetStatisticsQuery())
        assert result["completedFiles"] == 2

    async def test_failed_files_counted(self, handler, mock_repo):
        mock_repo.get_all.return_value = [
            _make_file(file_path="/a.mxf", status=FileStatus.FAILED),
        ]
        result = await handler.handle(GetStatisticsQuery())
        assert result["failedFiles"] == 1
        assert result["activeFiles"] == 0  # failed != active

    async def test_growing_files_counted(self, handler, mock_repo):
        mock_repo.get_all.return_value = [
            _make_file(file_path="/a.mxf", status=FileStatus.GROWING),
            _make_file(file_path="/b.mxf", status=FileStatus.READY_TO_START_GROWING),
            _make_file(file_path="/c.mxf", status=FileStatus.GROWING_COPY),
        ]
        result = await handler.handle(GetStatisticsQuery())
        assert result["growingFiles"] == 3

    async def test_total_size_bytes_summed(self, handler, mock_repo):
        mock_repo.get_all.return_value = [
            _make_file(file_path="/a.mxf", file_size=1000),
            _make_file(file_path="/b.mxf", file_size=2000),
        ]
        result = await handler.handle(GetStatisticsQuery())
        assert result["total_size_bytes"] == 3000

    async def test_same_path_counts_all_records(self, handler, mock_repo):
        """When two entries share the same file_path, both are counted."""
        older = _make_file(
            file_path="/dup.mxf",
            status=FileStatus.COMPLETED,
            discovered_at=datetime(2025, 1, 1),
        )
        newer = _make_file(
            file_path="/dup.mxf",
            status=FileStatus.COPYING,
            discovered_at=datetime(2025, 6, 1),
        )
        mock_repo.get_all.return_value = [older, newer]
        result = await handler.handle(GetStatisticsQuery())
        assert result["total_files"] == 2
        assert result["status_counts"]["Copying"] == 1
        assert result["status_counts"]["Completed"] == 1

    async def test_status_counts_all_statuses_present(self, handler, mock_repo):
        """All FileStatus values should be present in status_counts, even if 0."""
        mock_repo.get_all.return_value = [_make_file(status=FileStatus.READY)]
        result = await handler.handle(GetStatisticsQuery())
        for fs in FileStatus:
            assert fs.value in result["status_counts"]

    async def test_mixed_scenario(self, handler, mock_repo):
        mock_repo.get_all.return_value = [
            _make_file(file_path="/a.mxf", status=FileStatus.COPYING, file_size=5000),
            _make_file(file_path="/b.mxf", status=FileStatus.COMPLETED, file_size=3000),
            _make_file(file_path="/c.mxf", status=FileStatus.FAILED, file_size=1000),
            _make_file(file_path="/d.mxf", status=FileStatus.GROWING, file_size=2000),
            _make_file(file_path="/e.mxf", status=FileStatus.WAITING_FOR_SPACE, file_size=4000),
        ]
        result = await handler.handle(GetStatisticsQuery())
        assert result["total_files"] == 5
        assert result["completedFiles"] == 1
        assert result["failedFiles"] == 1
        assert result["growingFiles"] == 1
        assert result["activeFiles"] == 3  # 5 total - 1 completed - 1 failed
        assert result["total_size_bytes"] == 15000
