"""Tests for ReloadConfigCommandHandler — config reload from DB."""
import pytest
from unittest.mock import patch, MagicMock

from app.domains.shared.config_handlers import (
    ReloadConfigCommandHandler,
)
from app.domains.shared.settings_service import REQUIRES_RESTART
from app.domains.shared.commands import ReloadConfigCommand


def _make_settings(**overrides):
    """Create a MagicMock that behaves like a Pydantic Settings instance."""
    defaults = dict(
        source_directory="/src",
        destination_directory="/dst",
        log_file_path="logs/app.log",
        log_level="INFO",
        max_concurrent_copies=7,
    )
    defaults.update(overrides)
    s = MagicMock()
    s.model_fields = defaults.keys()
    for k, v in defaults.items():
        setattr(s, k, v)
    s.config_file_info = {"hostname": "test-host"}
    return s


@pytest.fixture
def handler():
    svc = MagicMock()
    svc.sync_to_settings.return_value = []  # no changes by default
    return ReloadConfigCommandHandler(settings_service=svc)


class TestReloadConfigSuccess:
    async def test_no_changes(self, handler):
        current = _make_settings()
        handler._settings_service.sync_to_settings.return_value = []

        with patch("app.domains.shared.config_handlers.get_settings", return_value=current):
            result = await handler.handle(ReloadConfigCommand())

        assert result["success"] is True
        assert result["changed_fields"] == []
        assert result["requires_restart"] == []

    async def test_field_changed(self, handler):
        current = _make_settings()
        handler._settings_service.sync_to_settings.return_value = ["max_concurrent_copies"]

        with patch("app.domains.shared.config_handlers.get_settings", return_value=current):
            result = await handler.handle(ReloadConfigCommand())

        assert result["success"] is True
        assert "max_concurrent_copies" in result["changed_fields"]
        assert result["requires_restart"] == []

    async def test_multiple_changed_fields(self, handler):
        current = _make_settings()
        handler._settings_service.sync_to_settings.return_value = ["source_directory", "max_concurrent_copies"]

        with patch("app.domains.shared.config_handlers.get_settings", return_value=current):
            result = await handler.handle(ReloadConfigCommand())

        assert len(result["changed_fields"]) == 2
        assert result["requires_restart"] == []

    async def test_sync_called_with_singleton(self, handler):
        current = _make_settings()

        with patch("app.domains.shared.config_handlers.get_settings", return_value=current):
            await handler.handle(ReloadConfigCommand())

        handler._settings_service.sync_to_settings.assert_called_once_with(current)

    async def test_result_contains_hostname(self, handler):
        current = _make_settings()

        with patch("app.domains.shared.config_handlers.get_settings", return_value=current):
            result = await handler.handle(ReloadConfigCommand())

        assert result["hostname"] == "test-host"


class TestReloadConfigFailure:
    async def test_sync_error(self, handler):
        current = _make_settings()
        handler._settings_service.sync_to_settings.side_effect = RuntimeError("DB gone")

        with patch("app.domains.shared.config_handlers.get_settings", return_value=current):
            result = await handler.handle(ReloadConfigCommand())

        assert result["success"] is False
        assert "DB gone" in result["message"]

    async def test_get_settings_error(self, handler):
        with patch(
            "app.domains.shared.config_handlers.get_settings",
            side_effect=RuntimeError("singleton gone"),
        ):
            result = await handler.handle(ReloadConfigCommand())

        assert result["success"] is False
        assert "singleton gone" in result["message"]
