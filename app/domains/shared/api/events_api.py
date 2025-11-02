"""
API endpoints for system event logs.
Provides access to GlobalEventLogger's in-memory event collection for UI visibility.
"""

from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from datetime import datetime

from app.dependencies import get_global_event_logger
from app.core.global_event_logger import GlobalEventLogger


router = APIRouter(prefix="/api/events", tags=["events"])


class EventResponse(BaseModel):
    """API response model for logged events"""
    timestamp: datetime
    level: str
    event_type: str
    details: Dict[str, Any]
    
    class Config:
        # Enable conversion from LoggedEvent dataclass
        from_attributes = True


@router.get("/", response_model=List[EventResponse])
async def get_events(
    limit: Optional[int] = Query(None, description="Maximum number of events to return"),
    level: Optional[str] = Query(None, description="Filter by event level (info, warning, error)"),
    event_logger: GlobalEventLogger = Depends(get_global_event_logger)
):
    """
    Get recent system events from the in-memory event log.
    
    - **limit**: Optional limit on number of events (default: all available)
    - **level**: Optional filter by event level (info, warning, error)
    """
    events = event_logger.get_events(limit=limit, level=level)
    
    # Convert LoggedEvent dataclasses to API response models
    return [
        EventResponse(
            timestamp=event.timestamp,
            level=event.level,
            event_type=event.event_type,
            details=event.context or {}
        )
        for event in events
    ]


@router.get("/stats", response_model=Dict[str, Any])
async def get_event_stats(
    event_logger: GlobalEventLogger = Depends(get_global_event_logger)
):
    """
    Get statistics about the event log.
    """
    all_events = event_logger.get_events()
    
    # Count by level
    level_counts = {}
    for event in all_events:
        level = event.level
        level_counts[level] = level_counts.get(level, 0) + 1
    
    # Count by event type
    type_counts = {}
    for event in all_events:
        event_type = event.event_type
        type_counts[event_type] = type_counts.get(event_type, 0) + 1
    
    return {
        "total_events": len(all_events),
        "max_capacity": event_logger.max_size,
        "levels": level_counts,
        "event_types": type_counts,
        "oldest_event": all_events[-1].timestamp.isoformat() if all_events else None,
        "newest_event": all_events[0].timestamp.isoformat() if all_events else None
    }


@router.get("/latest", response_model=Optional[EventResponse])
async def get_latest_event(
    level: Optional[str] = Query(None, description="Filter by event level"),
    event_logger: GlobalEventLogger = Depends(get_global_event_logger)
):
    """
    Get the most recent event, optionally filtered by level.
    """
    events = event_logger.get_events(limit=1, level=level)
    
    if not events:
        return None
    
    event = events[0]
    return EventResponse(
        timestamp=event.timestamp,
        level=event.level,
        event_type=event.event_type,
        details=event.context or {}
    )