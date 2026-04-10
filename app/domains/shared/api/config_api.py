"""
Config API endpoints for the Shared domain.

These endpoints handle system-wide configuration and application management
using CQRS patterns.
"""
import time
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.core.cqrs.command_bus import CommandBus
from app.core.cqrs.query_bus import QueryBus
from app.config import APP_VERSION, BUILD_TIME, APP_DIRECTORY
from app.dependencies.core import get_command_bus, get_query_bus
from ..commands import ReloadConfigCommand, RestartApplicationCommand, UpdateUserSettingsCommand
from ..queries import GetConfigInfoQuery, GetUserSettingsQuery


class PublicSettings(BaseModel):
    """Minimal system info exposed via API. User-editable settings will use a separate endpoint."""
    app_version: str = "unknown"
    build_time: str = "n/a"
    app_directory: str = "n/a"


router = APIRouter(prefix="/api/system", tags=["System & Config"])

# Simple in-memory rate limiter for restart
_last_restart_time: float = 0.0
_RESTART_COOLDOWN_SECONDS: float = 300.0  # 5 minutes


@router.get("/settings", response_model=PublicSettings)
async def read_settings():
    """Get minimal system info (build time, app directory)."""
    return PublicSettings(
        app_version=APP_VERSION,
        build_time=BUILD_TIME,
        app_directory=APP_DIRECTORY,
    )


@router.get("/config-info")
async def get_config_info(query_bus: QueryBus = Depends(get_query_bus)):
    """Get information about which configuration file is being used via CQRS Query."""
    return await query_bus.execute(GetConfigInfoQuery())


@router.post("/reload-config")
async def reload_config(command_bus: CommandBus = Depends(get_command_bus)):
    """Reload configuration from file via CQRS Command.

    Deprecated: UI button removed in Fase 3. Will be removed in Step C3.
    """
    return await command_bus.execute(ReloadConfigCommand())


@router.post("/restart-application")
async def restart_application(command_bus: CommandBus = Depends(get_command_bus)):
    """Restart the entire application via CQRS Command (rate-limited)."""
    global _last_restart_time
    now = time.monotonic()
    if now - _last_restart_time < _RESTART_COOLDOWN_SECONDS:
        remaining = int(_RESTART_COOLDOWN_SECONDS - (now - _last_restart_time))
        raise HTTPException(
            status_code=429,
            detail=f"Restart rate-limited. Try again in {remaining} seconds."
        )
    _last_restart_time = now
    return await command_bus.execute(RestartApplicationCommand())


# ---------------------------------------------------------------------------
# User Settings (editable via UI, persisted in SQLite)
# ---------------------------------------------------------------------------


class UserSettingsUpdate(BaseModel):
    """Request body for PUT /user-settings. Accepts any subset of the 12 user-editable keys."""
    source_directory: str | None = None
    destination_directory: str | None = None
    network_share_url: str | None = None
    enable_auto_mount: bool | None = None
    macos_mount_point: str | None = None
    tally_light_switch_ip: str | None = None
    output_folder_template_enabled: bool | None = None
    output_folder_rules: str | None = None
    output_folder_default_category: str | None = None
    output_folder_date_format: str | None = None
    output_folder_time_format: str | None = None
    max_concurrent_copies: int | None = Field(default=None, ge=1, le=32)
    justin_auto_stop_minutes: int | None = Field(default=None, ge=0, le=1440)
    brand_name: str | None = None


@router.get("/user-settings")
async def get_user_settings(query_bus: QueryBus = Depends(get_query_bus)):
    """Get all user-editable settings with metadata (type, default, requires_restart)."""
    return await query_bus.execute(GetUserSettingsQuery())


@router.put("/user-settings")
async def update_user_settings(
    body: UserSettingsUpdate,
    command_bus: CommandBus = Depends(get_command_bus),
):
    """Update one or more user-editable settings. Only non-null fields are applied."""
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Request body must contain at least one setting")
    result = await command_bus.execute(UpdateUserSettingsCommand(updates=updates))
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "Unknown error"))
    return result
