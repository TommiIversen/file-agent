"""
Storage monitoring API endpoints for the shared domain.
"""
from fastapi import APIRouter, Depends

from app.models import StorageInfo
from app.core.cqrs.query_bus import QueryBus
from app.dependencies.core import get_query_bus
from app.domains.shared.queries.storage_queries import (
    GetSourceStorageQuery,
    GetDestinationStorageQuery
)

router = APIRouter(prefix="/api/storage", tags=["storage"])


@router.get("/source", response_model=StorageInfo)
async def get_source_storage(
    query_bus: QueryBus = Depends(get_query_bus)
) -> StorageInfo:
    """
    Get source storage information.

    Returns:
        StorageInfo for source directory

    HTTP Status Codes:
        200: Normal operation
        507: Insufficient Storage (WARNING threshold exceeded)
        503: Service Unavailable (ERROR or CRITICAL status)
        404: Storage info not available (monitoring not started)
    """
    query = GetSourceStorageQuery()
    return await query_bus.execute(query)


@router.get("/destination", response_model=StorageInfo)
async def get_destination_storage(
    query_bus: QueryBus = Depends(get_query_bus)
) -> StorageInfo:
    """
    Get destination storage information.

    Returns:
        StorageInfo for destination directory

    HTTP Status Codes:
        200: Normal operation
        507: Insufficient Storage (WARNING threshold exceeded)
        503: Service Unavailable (ERROR or CRITICAL status)
        404: Storage info not available (monitoring not started)
    """
    query = GetDestinationStorageQuery()
    return await query_bus.execute(query)