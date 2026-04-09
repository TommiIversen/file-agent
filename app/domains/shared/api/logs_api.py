"""
Log file management API endpoints for the shared domain.
"""
from fastapi import APIRouter, Depends
from typing import List, Dict, Any

from app.core.cqrs.query_bus import QueryBus
from app.dependencies.core import get_query_bus
from app.domains.shared.queries.log_queries import (
    ListLogFilesQuery,
    GetLogContentQuery,
    GetLogContentChunkQuery,
    DownloadLogFileQuery
)

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("/", response_model=List[Dict[str, Any]])
async def list_log_files(
    query_bus: QueryBus = Depends(get_query_bus)
) -> List[Dict[str, Any]]:
    """
    List all available log files.
    
    Returns:
        List of log file information dictionaries
    """
    query = ListLogFilesQuery()
    return await query_bus.execute(query)


@router.get("/{filename}/content", response_model=Dict[str, Any])
async def get_log_content(
    filename: str,
    query_bus: QueryBus = Depends(get_query_bus)
) -> Dict[str, Any]:
    """
    Get the full content of a log file.
    
    Args:
        filename: Name of the log file
        
    Returns:
        Dictionary with file content and metadata
    """
    query = GetLogContentQuery(filename=filename)
    return await query_bus.execute(query)


@router.get("/{filename}/content/chunk", response_model=Dict[str, Any])
async def get_log_content_chunk(
    filename: str,
    start: int = 0,
    limit: int = 1000,
    query_bus: QueryBus = Depends(get_query_bus)
) -> Dict[str, Any]:
    """
    Get a chunk of log file content with pagination.
    
    Args:
        filename: Name of the log file
        start: Starting line number (0-based)
        limit: Maximum number of lines to return
        
    Returns:
        Dictionary with chunk content and pagination metadata
    """
    query = GetLogContentChunkQuery(filename=filename, start=start, limit=limit)
    return await query_bus.execute(query)


@router.get("/{filename}/download")
async def download_log_file(
    filename: str,
    query_bus: QueryBus = Depends(get_query_bus)
):
    """
    Download a log file.
    
    Args:
        filename: Name of the log file to download
        
    Returns:
        FileResponse for downloading the file
    """
    query = DownloadLogFileQuery(filename=filename)
    return await query_bus.execute(query)