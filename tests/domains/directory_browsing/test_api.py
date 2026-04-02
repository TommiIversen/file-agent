"""Tests for directory browsing API — scan_custom_directory endpoint."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from fastapi import HTTPException

from app.domains.directory_browsing.api import scan_custom_directory
from app.domains.directory_browsing.models import DirectoryScanResult


def _settings(source="/allowed/source", destination="/allowed/dest"):
    s = MagicMock()
    s.source_directory = source
    s.destination_directory = destination
    return s


def _scan_result(**kw):
    defaults = dict(
        path="/allowed/source",
        is_accessible=True,
        total_items=3,
        total_files=2,
        total_directories=1,
    )
    defaults.update(kw)
    return DirectoryScanResult(**defaults)


class TestScanCustomDirectoryValidation:
    async def test_empty_path_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            await scan_custom_directory(
                path="", query_bus=AsyncMock()
            )
        assert exc_info.value.status_code == 400

    async def test_whitespace_only_path_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            await scan_custom_directory(
                path="   ", query_bus=AsyncMock()
            )
        assert exc_info.value.status_code == 400

    async def test_path_outside_allowed_roots_raises_403(self):
        settings = _settings()
        with patch(
            "app.domains.directory_browsing.api.get_settings",
            return_value=settings,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await scan_custom_directory(
                    path="/not/allowed/path", query_bus=AsyncMock()
                )
            assert exc_info.value.status_code == 403


class TestScanCustomDirectorySuccess:
    async def test_source_subdirectory_allowed(self):
        settings = _settings()
        query_bus = AsyncMock()
        query_bus.execute.return_value = _scan_result()

        with patch(
            "app.domains.directory_browsing.api.get_settings",
            return_value=settings,
        ):
            result = await scan_custom_directory(
                path=settings.source_directory,
                query_bus=query_bus,
            )

        assert result.is_accessible is True
        query_bus.execute.assert_awaited_once()

    async def test_destination_subdirectory_allowed(self):
        settings = _settings()
        query_bus = AsyncMock()
        query_bus.execute.return_value = _scan_result(path=settings.destination_directory)

        with patch(
            "app.domains.directory_browsing.api.get_settings",
            return_value=settings,
        ):
            result = await scan_custom_directory(
                path=settings.destination_directory,
                query_bus=query_bus,
            )

        assert result.is_accessible is True

    async def test_passes_recursive_and_max_depth(self):
        settings = _settings()
        query_bus = AsyncMock()
        query_bus.execute.return_value = _scan_result()

        with patch(
            "app.domains.directory_browsing.api.get_settings",
            return_value=settings,
        ):
            await scan_custom_directory(
                path=settings.source_directory,
                recursive=False,
                max_depth=1,
                query_bus=query_bus,
            )

        query = query_bus.execute.call_args[0][0]
        assert query.recursive is False
        assert query.max_depth == 1


class TestScanCustomDirectoryErrors:
    async def test_value_error_raises_403(self):
        settings = _settings()
        query_bus = AsyncMock()
        query_bus.execute.side_effect = ValueError("forbidden path")

        with patch(
            "app.domains.directory_browsing.api.get_settings",
            return_value=settings,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await scan_custom_directory(
                    path=settings.source_directory,
                    query_bus=query_bus,
                )
            assert exc_info.value.status_code == 403

    async def test_unexpected_error_raises_500(self):
        settings = _settings()
        query_bus = AsyncMock()
        query_bus.execute.side_effect = RuntimeError("boom")

        with patch(
            "app.domains.directory_browsing.api.get_settings",
            return_value=settings,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await scan_custom_directory(
                    path=settings.source_directory,
                    query_bus=query_bus,
                )
            assert exc_info.value.status_code == 500
