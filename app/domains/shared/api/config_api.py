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
from app.dependencies import get_command_bus, get_query_bus
from ..commands import ReloadConfigCommand, RestartApplicationCommand
from ..queries import GetSettingsQuery, GetConfigInfoQuery


class PublicSettings(BaseModel):
    """Subset of settings safe to expose via API."""
    source_directory: str
    destination_directory: str
    file_stable_time_seconds: int
    polling_interval_seconds: int
    max_retry_attempts: int
    max_concurrent_copies: int
    storage_check_interval_seconds: int
    source_warning_threshold_gb: float
    source_critical_threshold_gb: float
    destination_warning_threshold_gb: float
    destination_critical_threshold_gb: float
    growing_file_min_size_mb: int
    growing_file_safety_margin_mb: int
    growing_file_growth_timeout_seconds: int
    chunk_size_kb: int
    log_level: str
    keep_files_hours: int
    justin_auto_stop_minutes: int
    justin_auto_stop_warning_minutes: int
    tally_light_switch_type: str
    enable_auto_mount: bool
    output_folder_template_enabled: bool


router = APIRouter(prefix="/api/system", tags=["System & Config"])

# Simple in-memory rate limiter for restart
_last_restart_time: float = 0.0
_RESTART_COOLDOWN_SECONDS: float = 300.0  # 5 minutes


@router.get("/settings", response_model=PublicSettings)
async def read_settings(query_bus: QueryBus = Depends(get_query_bus)):
    """Get current application settings (filtered for safety)."""
    full_settings = await query_bus.execute(GetSettingsQuery())
    return PublicSettings(**full_settings.model_dump())


@router.get("/config-info")
async def get_config_info(query_bus: QueryBus = Depends(get_query_bus)):
    """Get information about which configuration file is being used via CQRS Query."""
    return await query_bus.execute(GetConfigInfoQuery())


@router.post("/reload-config")
async def reload_config(command_bus: CommandBus = Depends(get_command_bus)):
    """Reload configuration from file via CQRS Command."""
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