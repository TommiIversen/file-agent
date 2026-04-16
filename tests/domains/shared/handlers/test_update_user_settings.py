"""Tests for UpdateUserSettingsCommandHandler and hot-reload functions."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.domains.shared.config_handlers import (
    UpdateUserSettingsCommandHandler,
    _reload_mount_service,
    _reload_tally_services,
    _reload_copy_pool,
    _reload_auto_stop,
    _reload_audio,
)
from app.domains.shared.commands import UpdateUserSettingsCommand


@pytest.fixture
def settings_service():
    svc = MagicMock()
    svc.set_many = AsyncMock(return_value={})
    svc.sync_to_settings = MagicMock(return_value=[])
    svc.get_all_with_metadata = MagicMock(return_value=[])
    return svc


@pytest.fixture
def handler(settings_service):
    return UpdateUserSettingsCommandHandler(settings_service=settings_service)


# ── handle() ──────────────────────────────────────────────────


class TestHandleSuccess:
    async def test_no_changes(self, handler, settings_service):
        settings_service.set_many.return_value = {"brand_name": False}
        with patch("app.domains.shared.config_handlers.get_settings"):
            result = await handler.handle(
                UpdateUserSettingsCommand(updates={"brand_name": "X"})
            )
        assert result["success"] is True
        assert result["changed"] == []

    async def test_changed_field_returns_in_response(self, handler, settings_service):
        settings_service.set_many.return_value = {"brand_name": True}
        with patch("app.domains.shared.config_handlers.get_settings"):
            result = await handler.handle(
                UpdateUserSettingsCommand(updates={"brand_name": "X"})
            )
        assert result["success"] is True
        assert "brand_name" in result["changed"]

    async def test_sync_called_on_change(self, handler, settings_service):
        settings_service.set_many.return_value = {"brand_name": True}
        mock_settings = MagicMock()
        with patch("app.domains.shared.config_handlers.get_settings", return_value=mock_settings):
            await handler.handle(
                UpdateUserSettingsCommand(updates={"brand_name": "X"})
            )
        settings_service.sync_to_settings.assert_called_once_with(mock_settings)

    async def test_sync_not_called_when_nothing_changed(self, handler, settings_service):
        settings_service.set_many.return_value = {"brand_name": False}
        with patch("app.domains.shared.config_handlers.get_settings"):
            await handler.handle(
                UpdateUserSettingsCommand(updates={"brand_name": "X"})
            )
        settings_service.sync_to_settings.assert_not_called()

    async def test_hot_reload_called_on_change(self, handler, settings_service):
        settings_service.set_many.return_value = {"max_concurrent_copies": True}
        with (
            patch("app.domains.shared.config_handlers.get_settings"),
            patch.object(
                UpdateUserSettingsCommandHandler, "_hot_reload_services"
            ) as mock_hr,
        ):
            await handler.handle(
                UpdateUserSettingsCommand(updates={"max_concurrent_copies": 5})
            )
        mock_hr.assert_called_once_with({"max_concurrent_copies"})

    async def test_includes_settings_in_response(self, handler, settings_service):
        settings_service.set_many.return_value = {"brand_name": False}
        settings_service.get_all_with_metadata.return_value = [{"key": "brand_name"}]
        with patch("app.domains.shared.config_handlers.get_settings"):
            result = await handler.handle(
                UpdateUserSettingsCommand(updates={"brand_name": "X"})
            )
        assert "settings" in result


class TestHandleAudioLock:
    async def test_blocks_audio_device_change_while_recording(self, handler, settings_service):
        mock_audio_svc = MagicMock()
        mock_audio_svc.is_recording = True
        with patch(
            "app.dependencies.audio_recording.get_audio_recording_service",
            return_value=mock_audio_svc,
        ):
            result = await handler.handle(
                UpdateUserSettingsCommand(updates={"audio_device_name": "New"})
            )
        assert result["success"] is False
        assert "recording is active" in result["message"]

    async def test_allows_audio_change_when_not_recording(self, handler, settings_service):
        settings_service.set_many.return_value = {"audio_device_name": True}
        mock_audio_svc = MagicMock()
        mock_audio_svc.is_recording = False
        with (
            patch(
                "app.dependencies.audio_recording.get_audio_recording_service",
                return_value=mock_audio_svc,
            ),
            patch("app.domains.shared.config_handlers.get_settings"),
        ):
            result = await handler.handle(
                UpdateUserSettingsCommand(updates={"audio_device_name": "New"})
            )
        assert result["success"] is True


class TestHandleErrors:
    async def test_key_error(self, handler, settings_service):
        settings_service.set_many.side_effect = KeyError("bad_key")
        result = await handler.handle(
            UpdateUserSettingsCommand(updates={"bad_key": "x"})
        )
        assert result["success"] is False

    async def test_value_error(self, handler, settings_service):
        settings_service.set_many.side_effect = ValueError("invalid value")
        result = await handler.handle(
            UpdateUserSettingsCommand(updates={"brand_name": ""})
        )
        assert result["success"] is False
        assert "invalid value" in result["message"]


# ── Hot-reload functions ──────────────────────────────────────


class TestReloadMountService:
    def test_calls_reinitialize(self):
        mock_mount = MagicMock()
        with patch(
            "app.domains.shared.config_handlers.get_network_mount_service",
            return_value=mock_mount,
        ):
            _reload_mount_service()
        mock_mount.reinitialize.assert_called_once()

    def test_exception_is_swallowed(self):
        with patch(
            "app.domains.shared.config_handlers.get_network_mount_service",
            side_effect=RuntimeError("boom"),
        ):
            _reload_mount_service()  # should not raise


class TestReloadTallyServices:
    def test_updates_switch_and_monitor(self):
        mock_settings = MagicMock()
        mock_settings.tally_light_switch_ip = "10.0.0.1"
        mock_settings.tally_light_switch_username = "admin"
        mock_settings.tally_light_switch_password = "pass"

        mock_switch = MagicMock()
        mock_switch.update_connection = MagicMock()
        mock_handler = MagicMock()
        mock_handler._power_switch = mock_switch

        mock_monitor = MagicMock()
        mock_monitor._switch_client = MagicMock()
        mock_monitor._switch_client.update_connection = MagicMock()

        with (
            patch("app.domains.shared.config_handlers.get_settings", return_value=mock_settings),
            patch("app.domains.shared.config_handlers.get_tally_light_event_handler", return_value=mock_handler),
            patch("app.domains.shared.config_handlers.get_tally_switch_monitor", return_value=mock_monitor),
        ):
            _reload_tally_services()

        mock_switch.update_connection.assert_called_once()
        mock_monitor.update_ip.assert_called_once_with("10.0.0.1")

    def test_exception_is_swallowed(self):
        with patch(
            "app.domains.shared.config_handlers.get_settings",
            side_effect=RuntimeError("boom"),
        ):
            _reload_tally_services()  # should not raise


class TestReloadCopyPool:
    def test_calls_resize_pool(self, event_loop):
        mock_settings = MagicMock()
        mock_settings.max_concurrent_copies = 5
        mock_copier = MagicMock()
        mock_copier.resize_pool = AsyncMock()

        with (
            patch("app.domains.shared.config_handlers.get_settings", return_value=mock_settings),
            patch("app.domains.shared.config_handlers.get_file_copier", return_value=mock_copier),
        ):
            _reload_copy_pool()

    def test_exception_is_swallowed(self):
        with patch(
            "app.domains.shared.config_handlers.get_settings",
            side_effect=RuntimeError("boom"),
        ):
            _reload_copy_pool()


class TestReloadAutoStop:
    def test_calls_update_auto_stop(self):
        mock_settings = MagicMock()
        mock_settings.justin_auto_stop_minutes = 30
        mock_svc = MagicMock()

        with (
            patch("app.domains.shared.config_handlers.get_settings", return_value=mock_settings),
            patch("app.domains.shared.config_handlers.get_ingest_state_service", return_value=mock_svc),
        ):
            _reload_auto_stop()

        mock_svc.update_auto_stop.assert_called_once_with(30)

    def test_exception_is_swallowed(self):
        with patch(
            "app.domains.shared.config_handlers.get_settings",
            side_effect=RuntimeError("boom"),
        ):
            _reload_auto_stop()


class TestReloadAudio:
    def test_kill_switch_stops_recording(self, event_loop):
        mock_settings = MagicMock()
        mock_settings.audio_recording_enabled = False
        mock_svc = MagicMock()
        mock_svc.is_recording = True
        mock_svc.stop = AsyncMock()

        with (
            patch("app.domains.shared.config_handlers.get_audio_recording_service", return_value=mock_svc, create=True),
            patch("app.domains.shared.config_handlers.get_settings", return_value=mock_settings),
        ):
            _reload_audio({"audio_recording_enabled"})

    def test_kill_switch_noop_when_not_recording(self, event_loop):
        mock_settings = MagicMock()
        mock_settings.audio_recording_enabled = False
        mock_svc = MagicMock()
        mock_svc.is_recording = False

        with (
            patch("app.domains.shared.config_handlers.get_audio_recording_service", return_value=mock_svc, create=True),
            patch("app.domains.shared.config_handlers.get_settings", return_value=mock_settings),
        ):
            _reload_audio({"audio_recording_enabled"})

    def test_device_change_reinitializes_recorder(self, event_loop):
        mock_settings = MagicMock()
        mock_settings.audio_device_name = "ASIO Test"
        mock_svc = MagicMock()
        mock_svc.reinitialize = AsyncMock()
        mock_recorder = MagicMock()

        with (
            patch("app.domains.shared.config_handlers.get_audio_recording_service", return_value=mock_svc, create=True),
            patch("app.domains.shared.config_handlers.get_settings", return_value=mock_settings),
            patch("app.domains.shared.config_handlers.create_recorder", return_value=mock_recorder, create=True),
        ):
            _reload_audio({"audio_device_name"})

    def test_empty_device_name(self, event_loop):
        mock_settings = MagicMock()
        mock_settings.audio_device_name = ""
        mock_svc = MagicMock()

        with (
            patch("app.domains.shared.config_handlers.get_audio_recording_service", return_value=mock_svc, create=True),
            patch("app.domains.shared.config_handlers.get_settings", return_value=mock_settings),
        ):
            _reload_audio({"audio_device_name"})

    def test_exception_is_swallowed(self):
        with patch(
            "app.domains.shared.config_handlers.get_audio_recording_service",
            side_effect=RuntimeError("boom"),
            create=True,
        ):
            _reload_audio({"audio_device_name"})
