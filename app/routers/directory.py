"""
Directory Scanner API Router - SRP compliant REST endpoints for directory scanning.

This router provides endpoints to scan source/destination directories
and return structured file/folder metadata for UI display.

Responsibilities:
- Expose directory scanning endpoints
- Handle async operations with proper error handling  
- Return structured JSON responses
- Integrate with DirectoryScannerService

Dependencies: DirectoryScannerService via dependency injection
"""

import logging
from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_directory_scanner
from app.services.directory_scanner import DirectoryScannerService, DirectoryScanResult


# Create router for directory scanning endpoints
router = APIRouter(
    prefix="/api/directory",
    tags=["directory"],
    responses={404: {"description": "Not found"}},
)


@router.get("/scan/source", response_model=DirectoryScanResult)
async def scan_source_directory(
    scanner: DirectoryScannerService = Depends(get_directory_scanner)
) -> DirectoryScanResult:
    """
    Scan the configured source directory for files and folders.
    
    Returns structured metadata including file sizes, timestamps, and directory info.
    Includes hidden files and handles network timeouts gracefully.
    
    Returns:
        DirectoryScanResult: Scan results with file/folder metadata
        
    Raises:
        HTTPException: On unexpected errors (timeouts are handled gracefully)
    """
    try:
        logging.info("API: Starting source directory scan")
        result = await scanner.scan_source_directory()
        
        logging.info(
            f"API: Source scan completed - {result.total_items} items found, "
            f"accessible: {result.is_accessible}"
        )
        
        return result
        
    except Exception as e:
        logging.error(f"API: Unexpected error during source directory scan: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to scan source directory: {str(e)}"
        )


@router.get("/scan/destination", response_model=DirectoryScanResult)
async def scan_destination_directory(
    scanner: DirectoryScannerService = Depends(get_directory_scanner)
) -> DirectoryScanResult:
    """
    Scan the configured destination directory for files and folders.
    
    Returns structured metadata including file sizes, timestamps, and directory info.
    Includes hidden files and handles network timeouts gracefully.
    
    Returns:
        DirectoryScanResult: Scan results with file/folder metadata
        
    Raises:
        HTTPException: On unexpected errors (timeouts are handled gracefully)
    """
    try:
        logging.info("API: Starting destination directory scan")
        result = await scanner.scan_destination_directory()
        
        logging.info(
            f"API: Destination scan completed - {result.total_items} items found, "
            f"accessible: {result.is_accessible}"
        )
        
        return result
        
    except Exception as e:
        logging.error(f"API: Unexpected error during destination directory scan: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to scan destination directory: {str(e)}"
        )


@router.get("/scan/custom")
async def scan_custom_directory(
    path: str,
    scanner: DirectoryScannerService = Depends(get_directory_scanner)
) -> DirectoryScanResult:
    """
    Scan a custom directory path for files and folders.
    
    Args:
        path: Directory path to scan
        
    Returns:
        DirectoryScanResult: Scan results with file/folder metadata
        
    Raises:
        HTTPException: On validation errors or unexpected failures
    """
    if not path or not path.strip():
        raise HTTPException(
            status_code=400,
            detail="Directory path is required"
        )
    
    try:
        logging.info(f"API: Starting custom directory scan: {path}")
        result = await scanner.scan_custom_directory(path.strip())
        
        logging.info(
            f"API: Custom scan completed for {path} - {result.total_items} items found, "
            f"accessible: {result.is_accessible}"
        )
        
        return result
        
    except Exception as e:
        logging.error(f"API: Unexpected error during custom directory scan {path}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to scan directory {path}: {str(e)}"
        )


@router.get("/scanner/info")
async def get_scanner_info(
    scanner: DirectoryScannerService = Depends(get_directory_scanner)
) -> dict:
    """
    Get directory scanner service configuration and status information.
    
    Returns:
        Dict: Service configuration including timeouts and configured paths
    """
    try:
        return scanner.get_service_info()
        
    except Exception as e:
        logging.error(f"API: Error getting scanner info: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get scanner info: {str(e)}"
        )