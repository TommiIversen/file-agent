import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

# Importer fra de nye, domæne-specifikke placeringer
from app.dependencies.core import get_query_bus, get_settings
from app.core.cqrs.query_bus import QueryBus
from app.domains.directory_browsing.models import DirectoryScanResult
from app.domains.directory_browsing.queries import (
    ScanSourceDirectoryQuery,
    ScanDestinationDirectoryQuery,
    ScanCustomDirectoryQuery,
    GetScannerInfoQuery,
)

directory_router = APIRouter(
    prefix="/api/directory",
    tags=["directory"],
)

@directory_router.get("/scan/source", response_model=DirectoryScanResult)
async def scan_source_directory(
    recursive: bool = True,
    max_depth: int = 3,
    query_bus: QueryBus = Depends(get_query_bus) # <-- ÆNDRET
) -> DirectoryScanResult:
    try:
        # Opret en Query i stedet for at kalde en service
        query = ScanSourceDirectoryQuery(recursive=recursive, max_depth=max_depth)
        result = await query_bus.execute(query) # <-- ÆNDRET
        
        logging.info(
            f"API: Source scan completed - {result.total_items} items found, "
            f"accessible: {result.is_accessible}"
        )
        return result
        
    except Exception as e:
        logging.error(f"API: Unexpected error during source directory scan: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")



@directory_router.get("/scan/destination", response_model=DirectoryScanResult)
async def scan_destination_directory(
    recursive: bool = True,
    max_depth: int = 3,
    query_bus: QueryBus = Depends(get_query_bus)
) -> DirectoryScanResult:
    try:
        query = ScanDestinationDirectoryQuery(recursive=recursive, max_depth=max_depth)
        result = await query_bus.execute(query)

        logging.info(
            f"API: Destination scan completed - {result.total_items} items found, "
            f"accessible: {result.is_accessible}"
        )
        return result

    except Exception as e:
        logging.error(f"API: Unexpected error during destination directory scan: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@directory_router.get("/scan/custom")
async def scan_custom_directory(
    path: str,
    recursive: bool = True,
    max_depth: int = 3,
    query_bus: QueryBus = Depends(get_query_bus)
) -> DirectoryScanResult:
    if not path or not path.strip():
        raise HTTPException(status_code=400, detail="Directory path is required")

    # Path traversal protection: restrict to source/destination directories
    settings = get_settings()
    allowed_roots = [
        Path(settings.source_directory).resolve(),
        Path(settings.destination_directory).resolve(),
    ]
    requested = Path(path.strip()).resolve()
    if not any(requested == root or requested.is_relative_to(root) for root in allowed_roots):
        raise HTTPException(status_code=403, detail="Path is outside allowed directories")

    try:
        query = ScanCustomDirectoryQuery(
            path=path.strip(), recursive=recursive, max_depth=max_depth
        )
        result = await query_bus.execute(query)

        logging.info(
            f"API: Custom scan completed for {path} - {result.total_items} items found, "
            f"accessible: {result.is_accessible}"
        )
        return result

    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logging.error(f"API: Unexpected error during custom directory scan: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@directory_router.get("/scanner/info")
async def get_scanner_info(
    query_bus: QueryBus = Depends(get_query_bus)
) -> dict:
    try:
        query = GetScannerInfoQuery()
        return await query_bus.execute(query)

    except Exception as e:
        logging.error(f"API: Error getting scanner info: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to get scanner info"
        )

