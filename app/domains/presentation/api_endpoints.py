import asyncio
import logging
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, Query

from app.core.cqrs.query_bus import QueryBus
from app.dependencies import get_query_bus, get_tally_switch_monitor, get_ingest_monitor_worker
from app.domains.presentation.queries import GetAllFilesQuery, GetRecentFilesQuery, GetStatisticsQuery, GetStorageStatusQuery


presentation_router = APIRouter()


def _serialize_tracked_file(tracked_file) -> Dict[str, Any]:
    """Helper to serialize a single TrackedFile object for the API response."""
    data = tracked_file.model_dump(mode="json")
    data["file_size_mb"] = round(tracked_file.file_size / (1024 * 1024), 2)
    return data


@presentation_router.get("/api/initial-state", tags=["Presentation"])
async def get_initial_state(query_bus: QueryBus = Depends(get_query_bus)) -> Dict[str, Any]:
    """
    Provides the complete initial state for the frontend application.
    This is called once by the client after the WebSocket connection is established.
    """
    logging.info("Fetching initial state for frontend...")

    # Execute queries in parallel to fetch all necessary data
    all_files, statistics, storage_status = await asyncio.gather(
        query_bus.execute(GetRecentFilesQuery(limit=20)),
        query_bus.execute(GetStatisticsQuery()),
        query_bus.execute(GetStorageStatusQuery()),
    )

    logging.info(f"Initial state fetched: {len(all_files)} files, {statistics['total_files']} stats entries.")

    # The scanner status is not yet in a query, so we'll hardcode it for now
    # This should be moved to a query in a future step.
    scanner_status = {"scanning": True, "paused": False}

    # Get tally switch status from monitor service
    tally_status = None
    try:
        tally_service = get_tally_switch_monitor()
        if tally_service and tally_service.current_status:
            status = tally_service.current_status
            tally_status = {
                "is_online": status.is_online,
                "switch_type": "IP Power 9255",
                "ip_address": tally_service._ip_address,
                "last_checked": status.last_checked.isoformat() if status.last_checked else None,
                "error_message": status.error_message,
                "is_monitoring": tally_service.is_monitoring
            }
        else:
            tally_status = {
                "is_online": False,
                "switch_type": "IP Power 9255", 
                "ip_address": "192.168.1.100",
                "last_checked": None,
                "error_message": "Not yet checked",
                "is_monitoring": False
            }
    except Exception as e:
        # Service not available or error occurred
        tally_status = {
            "is_online": None,
            "switch_type": "unknown",
            "ip_address": "unknown", 
            "last_checked": None,
            "error_message": f"Service error: {str(e)}",
            "is_monitoring": False
        }

    # Get ingest connection status from monitor worker
    ingest_connection_status = None
    try:
        ingest_worker = get_ingest_monitor_worker()
        if ingest_worker:
            ingest_connection_status = {
                "is_connected": ingest_worker.get_connection_status()
            }
        else:
            ingest_connection_status = {
                "is_connected": False
            }
    except Exception as e:
        # Service not available or error occurred
        ingest_connection_status = {
            "is_connected": False
        }

    return {
        "files": [_serialize_tracked_file(f) for f in all_files],
        "statistics": statistics,
        "storage": storage_status,
        "scanner": scanner_status,
        "tally_switch": tally_status,
        "ingest_connection": ingest_connection_status,
    }


@presentation_router.get("/api/files", tags=["Presentation"])
async def get_files(
    limit: int = Query(20, description="Number of files to return"),
    offset: int = Query(0, description="Offset for pagination"),
    status: Optional[str] = Query(None, description="Filter by file status"),
    query_bus: QueryBus = Depends(get_query_bus),
) -> List[Dict[str, Any]]:
    """
    Get files with offset-based pagination.
    
    Used by infinite scroll to load older files beyond the initial batch.
    """
    files = await query_bus.execute(
        GetRecentFilesQuery(limit=limit, offset=offset, status=status)
    )
    return [_serialize_tracked_file(f) for f in files]
