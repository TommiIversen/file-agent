"""
Handlers for Shared Domain - System-wide functionality.

These handlers implement the business logic for system configuration
and application management operations.
"""
import logging
import os
import asyncio
from app.config import Settings
from app.dependencies import get_settings
from .commands import ReloadConfigCommand, RestartApplicationCommand
from .queries import GetSettingsQuery, GetConfigInfoQuery

# Fields that are bound at startup and cannot take effect until restart.
REQUIRES_RESTART_FIELDS: set[str] = {
    "source_directory",
    "destination_directory",
    "log_file_path",
    "log_level",
    "max_concurrent_copies",
}


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
    """Handler for reloading application configuration.

    Mutates the existing Settings singleton in-place so every service
    that already holds a reference sees the updated values immediately.
    """

    async def handle(self, command: ReloadConfigCommand) -> dict:
        """Handle ReloadConfigCommand and reload configuration from file."""
        try:
            logging.info("Config reload requested via CQRS Command", extra={"operation": "cqrs_reload_config"})

            # Grab the existing singleton that all services reference
            current = get_settings()

            # Parse a fresh Settings from the config file on disk
            fresh = Settings()

            # Overwrite every field on the existing instance in-place
            # so all holders of the old reference see new values.
            changed: list[str] = []
            for field_name in fresh.model_fields:
                old_val = getattr(current, field_name)
                new_val = getattr(fresh, field_name)
                if old_val != new_val:
                    object.__setattr__(current, field_name, new_val)
                    changed.append(field_name)

            needs_restart = [f for f in changed if f in REQUIRES_RESTART_FIELDS]

            config_info = current.config_file_info
            logging.info(
                f"Configuration reloaded from: {config_info['active_config_file']} "
                f"({len(changed)} field(s) changed: {', '.join(changed) or 'none'})"
            )
            if needs_restart:
                logging.info(f"Restart required for: {', '.join(needs_restart)}")

            return {
                "success": True,
                "message": "Configuration reloaded successfully",
                "config_file": config_info["active_config_file"],
                "hostname": config_info["hostname"],
                "changed_fields": changed,
                "requires_restart": needs_restart,
            }

        except Exception as e:
            logging.error(f"Failed to reload configuration: {e}")
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
            logging.error(f"Failed to restart application: {e}")
            return {"success": False, "message": f"Failed to restart application: {str(e)}"}