"""
API endpoints for system event logs.
Provides access to persisted events from SQLite via GlobalEventLogger.
"""

from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from datetime import datetime, date
import csv
import io

from app.dependencies import get_global_event_logger
from app.core.global_event_logger import GlobalEventLogger


router = APIRouter(prefix="/api/events", tags=["events"])

PAGE_SIZE = 50


class EventResponse(BaseModel):
    """API response model for logged events"""
    id: Optional[int] = None
    timestamp: datetime
    level: str
    event_type: str
    details: Dict[str, Any]
    
    class Config:
        from_attributes = True


@router.get("/", response_model=List[EventResponse])
async def get_events(
    limit: int = Query(PAGE_SIZE, description="Number of events to return"),
    level: Optional[str] = Query(None, description="Filter by event level (info, warning, error)"),
    from_date: Optional[datetime] = Query(None, description="Only return events from this datetime onwards (ISO 8601)"),
    before_id: Optional[int] = Query(None, description="Cursor: only return events with id < this value (for infinite scroll)"),
    event_logger: GlobalEventLogger = Depends(get_global_event_logger)
):
    """
    Get system events with cursor-based pagination.
    
    First call: GET /api/events/?limit=50 → returns newest 50 events.
    Next page: GET /api/events/?limit=50&before_id=<last event id> → next 50 older.
    """
    events = await event_logger.get_events(
        limit=limit, level=level, from_date=from_date, before_id=before_id
    )
    
    return [
        EventResponse(
            id=event.id,
            timestamp=event.timestamp,
            level=event.level,
            event_type=event.event_type,
            details=event.context or {}
        )
        for event in events
    ]


@router.get("/download")
async def download_events_for_day(
    day: date = Query(..., description="Date to download events for (YYYY-MM-DD)"),
    event_logger: GlobalEventLogger = Depends(get_global_event_logger)
):
    """Download all events for a specific day as CSV."""
    from_dt = datetime(day.year, day.month, day.day, 0, 0, 0)
    to_dt = datetime(day.year, day.month, day.day, 23, 59, 59, 999999)
    
    # Get all events for the day (from_date gives us >= start, we filter <= end in Python)
    events = await event_logger.get_events(from_date=from_dt)
    day_events = [e for e in events if e.timestamp <= to_dt]
    # Reverse to chronological order for CSV
    day_events.reverse()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Timestamp", "Level", "Event Type", "Message", "Details"])
    for event in day_events:
        details = ""
        if event.context:
            details = " | ".join(f"{k}: {v}" for k, v in event.context.items())
        writer.writerow([
            event.timestamp.isoformat(),
            event.level,
            event.event_type,
            event.message,
            details,
        ])
    
    filename = f"events-{day.isoformat()}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )