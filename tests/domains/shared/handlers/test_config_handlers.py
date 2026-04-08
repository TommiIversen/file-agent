"""Tests for ReloadConfigCommandHandler — config reload logic."""
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
        api_port=8080,
    )
    defaults.update(overrides)
    s = MagicMock()
    s.model_fields = defaults.keys()
    for k, v in defaults.items():
        setattr(s, k, v)
    s.config_file_info = {
        "active_config_file": "settings.env",
        "hostname": "test-host",
    }
    return s


@pytest.fixture
def handler():
    return ReloadConfigCommandHandler()


class TestReloadConfigSuccess:
    async def test_no_changes(self, handler):
        current = _make_settings()
        fresh = _make_settings()  # identical

        with (
            patch("app.domains.shared.config_handlers.get_settings", return_value=current),
            patch("app.domains.shared.config_handlers.Settings", return_value=fresh),
        ):
            result = await handler.handle(ReloadConfigCommand())

        assert result["success"] is True
        assert result["changed_fields"] == []
        assert result["requires_restart"] == []

    async def test_non_restart_field_changed(self, handler):
        current = _make_settings(api_port=8080)
        fresh = _make_settings(api_port=9090)

        with (
            patch("app.domains.shared.config_handlers.get_settings", return_value=current),
            patch("app.domains.shared.config_handlers.Settings", return_value=fresh),
        ):
            result = await handler.handle(ReloadConfigCommand())

        assert result["success"] is True
        assert "api_port" in result["changed_fields"]
        assert result["requires_restart"] == []

    async def test_restart_field_changed(self, handler):
        current = _make_settings(source_directory="/old")
        fresh = _make_settings(source_directory="/new")

        with (
            patch("app.domains.shared.config_handlers.get_settings", return_value=current),
            patch("app.domains.shared.config_handlers.Settings", return_value=fresh),
        ):
            result = await handler.handle(ReloadConfigCommand())

        assert result["success"] is True
        assert "source_directory" in result["changed_fields"]
        assert "source_directory" in result["requires_restart"]

    async def test_multiple_changed_fields(self, handler):
        current = _make_settings(source_directory="/old", api_port=8080)
        fresh = _make_settings(source_directory="/new", api_port=9090)

        with (
            patch("app.domains.shared.config_handlers.get_settings", return_value=current),
            patch("app.domains.shared.config_handlers.Settings", return_value=fresh),
        ):
            result = await handler.handle(ReloadConfigCommand())

        assert len(result["changed_fields"]) == 2
        assert "source_directory" in result["requires_restart"]

    async def test_in_place_mutation(self, handler):
        """Verify the existing singleton is mutated, not replaced."""
        current = _make_settings(api_port=8080)
        fresh = _make_settings(api_port=9090)

        with (
            patch("app.domains.shared.config_handlers.get_settings", return_value=current),
            patch("app.domains.shared.config_handlers.Settings", return_value=fresh),
        ):
            await handler.handle(ReloadConfigCommand())

        # object.__setattr__ was used to mutate `current` in-place
        assert current.api_port == 9090

    async def test_result_contains_config_file_info(self, handler):
        current = _make_settings()
        fresh = _make_settings()

        with (
            patch("app.domains.shared.config_handlers.get_settings", return_value=current),
            patch("app.domains.shared.config_handlers.Settings", return_value=fresh),
        ):
            result = await handler.handle(ReloadConfigCommand())

        assert result["config_file"] == "settings.env"
        assert result["hostname"] == "test-host"


class TestReloadConfigFailure:
    async def test_settings_parse_error(self, handler):
        current = _make_settings()

        with (
            patch("app.domains.shared.config_handlers.get_settings", return_value=current),
            patch(
                "app.domains.shared.config_handlers.Settings",
                side_effect=ValueError("bad env"),
            ),
        ):
            result = await handler.handle(ReloadConfigCommand())

        assert result["success"] is False
        assert "bad env" in result["message"]

    async def test_get_settings_error(self, handler):
        with patch(
            "app.domains.shared.config_handlers.get_settings",
            side_effect=RuntimeError("singleton gone"),
        ):
            result = await handler.handle(ReloadConfigCommand())

        assert result["success"] is False
        assert "singleton gone" in result["message"]
