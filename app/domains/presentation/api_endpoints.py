import asyncio
import logging
from typing import Dict, Any

from fastapi import APIRouter, Depends

from app.core.cqrs.query_bus import QueryBus
from app.dependencies import get_query_bus
from app.domains.presentation.queries import GetAllFilesQuery, GetStatisticsQuery, GetStorageStatusQuery


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
        query_bus.execute(GetAllFilesQuery()),
        query_bus.execute(GetStatisticsQuery()),
        query_bus.execute(GetStorageStatusQuery()),
    )

    logging.info(f"Initial state fetched: {len(all_files)} files, {statistics['total_files']} stats entries.")

    # The scanner status is not yet in a query, so we'll hardcode it for now
    # This should be moved to a query in a future step.
    scanner_status = {"scanning": True, "paused": False}

    return {
        "files": [_serialize_tracked_file(f) for f in all_files],
        "statistics": statistics,
        "storage": storage_status,
        "scanner": scanner_status,
    }
