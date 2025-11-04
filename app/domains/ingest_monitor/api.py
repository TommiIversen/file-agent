"""
Ingest Monitor API Endpoints

This module provides REST API endpoints for retrieving ingest monitor data.
"""

from fastapi import APIRouter, Depends
from typing import Dict, Any

from app.core.cqrs.query_bus import QueryBus
from app.dependencies import get_query_bus
from .queries import GetIngestStatusQuery


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