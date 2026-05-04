"""
Handlers for Shared Domain - System-wide functionality.

These handlers implement the business logic for system configuration
and application management operations.
"""
import logging
import os
import asyncio
from typing import Any
from app.config import Settings
from app.dependencies.core import get_settings
from app.dependencies.storage import get_network_mount_service
from app.dependencies.tally import get_tally_light_event_handler, get_tally_switch_monitor
from app.dependencies.file_processing import get_file_copier
from app.dependencies.ingest import get_ingest_state_service
from .commands import ReloadConfigCommand, RestartApplicationCommand, UpdateUserSettingsCommand
from .queries import GetSettingsQuery, GetConfigInfoQuery, GetUserSettingsQuery
from .settings_service import UserSettingsService, REQUIRES_RESTART

_MOUNT_SETTINGS = {"network_share_url", "enable_auto_mount", "macos_mount_point"}
_TALLY_SETTINGS = {"tally_light_switch_ip"}
_COPY_POOL_SETTINGS = {"max_concurrent_copies"}
_AUTO_STOP_SETTINGS = {"justin_auto_stop_minutes"}
_AUDIO_SETTINGS = {"audio_device_name", "audio_sample_rate", "audio_tracks"}
_AUDIO_LOCKED_WHILE_RECORDING = {"audio_device_name", "audio_sample_rate", "audio_tracks"}


class GetSettingsQueryHandler:
    """Handler for retrieving current application settings."""
    
    def __init__(self, settings: Settings):
        self._settings = settings

    async def handle(self, query: GetSettingsQuery) -> Settings:
        """Handle GetSettingsQuery and return current settings."""
        logging.info("Henter settings via CQRS Query", extra={"operation": "cqrs_get_settings"})
        return self._settings


class GetConfigInfoQueryHandler:
    """Handler for retrieving configuration file information."""
    
    def __init__(self, settings: Settings):
        self._settings = settings

    async def handle(self, query: GetConfigInfoQuery) -> dict:
        """Handle GetConfigInfoQuery and return config file information."""
        logging.info("Henter config info via CQRS Query", extra={"operation": "cqrs_get_config_info"})
        return self._settings.config_file_info


class ReloadConfigCommandHandler:
    """Handler for reloading application configuration from database.

    Reloads DB-backed settings and syncs them into the Settings singleton
    so every service that holds a reference sees the updated values.
    """

    def __init__(self, settings_service: UserSettingsService) -> None:
        self._settings_service = settings_service

    async def handle(self, command: ReloadConfigCommand) -> dict:
        """Handle ReloadConfigCommand and reload configuration from database."""
        try:
            logging.info("Config reload requested via CQRS Command", extra={"operation": "cqrs_reload_config"})

            current = get_settings()

            # Reload from DB and sync into the singleton
            changed = self._settings_service.sync_to_settings(current)

            config_info = current.config_file_info
            logging.info(
                f"Configuration reloaded from database "
                f"({len(changed)} field(s) changed: {', '.join(changed) or 'none'})"
            )

            return {
                "success": True,
                "message": "Configuration reloaded successfully",
                "hostname": config_info["hostname"],
                "changed_fields": changed,
                "requires_restart": [f for f in changed if f in REQUIRES_RESTART],
            }

        except Exception as e:
            logging.error(f"Failed to reload configuration: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Failed to reload configuration: {str(e)}",
            }


class RestartApplicationCommandHandler:
    """Handler for restarting the application.

    Exits the process with code 0.  The external process manager
    (launchd on macOS, systemd on Linux, or uvicorn --reload in dev)
    is responsible for bringing it back up.
    """

    async def handle(self, command: RestartApplicationCommand) -> dict:
        """Handle RestartApplicationCommand and initiate application restart."""
        try:
            logging.info("Application restart requested via CQRS Command", extra={"operation": "cqrs_restart_app"})

            async def delayed_exit():
                await asyncio.sleep(1)  # Give time for HTTP response to be sent
                logging.info("Shutting down for restart...")
                os._exit(0)

            asyncio.create_task(delayed_exit())

            return {
                "success": True,
                "message": "Application shutting down — process manager will restart it.",
            }

        except Exception as e:
            logging.error(f"Failed to restart application: {e}", exc_info=True)
            return {"success": False, "message": f"Failed to restart application: {str(e)}"}


class GetUserSettingsQueryHandler:
    """Handler for retrieving all user-editable settings with metadata."""

    def __init__(self, settings_service: UserSettingsService) -> None:
        self._service = settings_service

    async def handle(self, query: GetUserSettingsQuery) -> dict[str, Any]:
        return {
            "settings": self._service.get_all_with_metadata(),
        }


class UpdateUserSettingsCommandHandler:
    """Handler for updating user-editable settings in the database."""

    def __init__(self, settings_service: UserSettingsService) -> None:
        self._service = settings_service

    async def handle(self, command: UpdateUserSettingsCommand) -> dict[str, Any]:
        try:
            # State-guard: block audio device/rate/tracks changes while recording
            locked = set(command.updates) & _AUDIO_LOCKED_WHILE_RECORDING
            if locked:
                from app.dependencies.audio_recording import get_audio_recording_service
                if get_audio_recording_service().is_recording:
                    return {
                        "success": False,
                        "message": f"Cannot change {', '.join(sorted(locked))} while recording is active",
                    }

            results = await self._service.set_many(command.updates)
            changed = [k for k, v in results.items() if v]
            needs_restart = [k for k in changed if k in REQUIRES_RESTART]

            # Sync all changed settings into the Settings singleton
            if changed:
                self._service.sync_to_settings(get_settings())
                self._hot_reload_services(set(changed))

            logging.info(
                "User settings updated: %s changed, restart needed: %s",
                ", ".join(changed) or "none",
                ", ".join(needs_restart) or "none",
            )

            return {
                "success": True,
                "changed": changed,
                "requires_restart": needs_restart,
                "settings": self._service.get_all_with_metadata(),
            }
        except (KeyError, ValueError) as e:
            return {"success": False, "message": str(e)}

    @staticmethod
    def _hot_reload_services(changed: set[str]) -> None:
        """Reinitialize services whose baked config just changed."""
        if changed & _MOUNT_SETTINGS:
            _reload_mount_service()

        if changed & _TALLY_SETTINGS:
            _reload_tally_services()

        if changed & _COPY_POOL_SETTINGS:
            _reload_copy_pool()

        if changed & _AUTO_STOP_SETTINGS:
            _reload_auto_stop()

        if changed & (_AUDIO_SETTINGS | {"audio_recording_enabled"}):
            _reload_audio(changed)


def _reload_mount_service() -> None:
    try:
        get_network_mount_service().reinitialize()
    except Exception:
        logging.warning("Could not reinitialize network mount service", exc_info=True)


def _reload_tally_services() -> None:
    try:
        settings = get_settings()
        ip = settings.tally_light_switch_ip

        handler = get_tally_light_event_handler()
        switch = handler._power_switch
        if hasattr(switch, "update_connection"):
            switch.update_connection(
                ip_address=ip,
                username=settings.tally_light_switch_username,
                password=settings.tally_light_switch_password,
            )

        monitor = get_tally_switch_monitor()
        monitor.update_ip(ip)
        if hasattr(monitor._switch_client, "update_connection"):
            monitor._switch_client.update_connection(
                ip_address=ip,
                username=settings.tally_light_switch_username,
                password=settings.tally_light_switch_password,
            )
        logging.info("Tally light IP hot-reloaded to %s", ip)
    except Exception:
        logging.warning("Could not reinitialize tally services", exc_info=True)


def _reload_copy_pool() -> None:
    try:
        new_count = get_settings().max_concurrent_copies
        copier = get_file_copier()
        asyncio.ensure_future(copier.resize_pool(new_count))
    except Exception:
        logging.warning("Could not resize copy worker pool", exc_info=True)


def _reload_auto_stop() -> None:
    try:
        minutes = get_settings().justin_auto_stop_minutes
        get_ingest_state_service().update_auto_stop(minutes)
    except Exception:
        logging.warning("Could not update auto-stop config", exc_info=True)


def _reload_audio(changed: set[str]) -> None:
    try:
        from app.dependencies.audio_recording import get_audio_recording_service
        from app.domains.audio_recording.recorder.factory import create_recorder
        service = get_audio_recording_service()
        settings = get_settings()

        # Kill-switch: disable → stop immediately
        if "audio_recording_enabled" in changed and not settings.audio_recording_enabled:
            if service.is_recording:
                asyncio.ensure_future(service.stop())
            logging.info("Audio recording disabled via kill-switch")
            return

        # Reinitialize recorder on device/rate change
        if changed & _AUDIO_SETTINGS:
            device_name = settings.audio_device_name
            if device_name:
                recorder = create_recorder(device_name)
                asyncio.ensure_future(service.reinitialize(recorder))
                logging.info("Audio recorder reinitialized for device: %s", device_name)
            else:
                logging.info("Audio device cleared — recorder removed")
    except Exception:
        logging.warning("Could not reinitialize audio recorder", exc_info=True)
