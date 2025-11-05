"""
Ingest Monitor API Endpoints

This module provides REST API endpoints for retrieving ingest monitor data.
"""

from fastapi import APIRouter, Depends
from typing import Dict, Any

from app.core.cqrs.query_bus import QueryBus
from app.core.cqrs.command_bus import CommandBus
from app.dependencies import get_query_bus, get_command_bus
from .queries import GetIngestStatusQuery
from .commands import ClearAllChannelErrorsCommand


# Router for ingest monitor endpoints
router = APIRouter(prefix="/api/ingest", tags=["Ingest Monitor"])


@router.get("/status", response_model=Dict[str, Any])
async def get_ingest_status(
    query_bus: QueryBus = Depends(get_query_bus)
) -> Dict[str, Any]:
    """
    Get live status for all Just In Engine ingest channels.
    
    Returns a snapshot of the current state of all monitored channels,
    including recording status, signal availability, and error conditions.
    
    This endpoint returns cached data from the IngestMonitorService for
    lightning-fast response times.
    
    Returns:
        Dict containing channel statuses with the following structure:
        {
            "KAM_1": {
                "name": "KAM_1",
                "is_recording": bool,
                "has_signal": bool,
                "has_errors": bool,
                "last_errors": [...],
                "frames": int,
                "hours": int,
                "minutes": int,
                "seconds": int
            },
            ...
        }
    """
    return await query_bus.execute(GetIngestStatusQuery())


@router.post("/clear-all-errors", response_model=Dict[str, Any])
async def clear_all_channel_errors(
    command_bus: CommandBus = Depends(get_command_bus)
) -> Dict[str, Any]:
    """
    Clear errors for all Just In Engine ingest channels.
    
    This endpoint will:
    1. Clear errors on Just In Engine for all active channels
    2. Update local state cache to reflect cleared errors  
    3. Publish events to update UI immediately
    
    Returns:
        Dict containing operation result:
        {
            "success": bool,
            "channels_cleared": int,
            "total_channels": int,
            "message": str
        }
    """
    return await command_bus.execute(ClearAllChannelErrorsCommand())