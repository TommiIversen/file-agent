"""
Config API endpoints for the Shared domain.

These endpoints handle system-wide configuration and application management
using CQRS patterns.
"""
from fastapi import APIRouter, Depends
from app.core.cqrs.command_bus import CommandBus
from app.core.cqrs.query_bus import QueryBus
from app.dependencies import get_command_bus, get_query_bus
from app.config import Settings
from ..commands import ReloadConfigCommand, RestartApplicationCommand
from ..queries import GetSettingsQuery, GetConfigInfoQuery

router = APIRouter(prefix="/api/system", tags=["System & Config"])


@router.get("/settings", response_model=Settings)
async def read_settings(query_bus: QueryBus = Depends(get_query_bus)):
    """Get current application settings via CQRS Query."""
    return await query_bus.execute(GetSettingsQuery())


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
    """Restart the entire application via CQRS Command."""
    return await command_bus.execute(RestartApplicationCommand())