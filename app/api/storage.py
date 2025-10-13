from fastapi import APIRouter, HTTPException, Depends, status

from ..dependencies import get_storage_monitor
from ..services.storage_monitor import StorageMonitorService
from ..models import StorageInfo, StorageStatus

router = APIRouter(prefix="/api", tags=["storage"])

@router.get("/storage/source", response_model=StorageInfo)
async def get_source_storage(
    storage_monitor: StorageMonitorService = Depends(get_storage_monitor)
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
    source_info = storage_monitor.get_source_info()
    
    if source_info is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source storage information not available. Monitoring may not be started."
        )    
    if source_info.status == StorageStatus.CRITICAL:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Critical source storage issue: {source_info.error_message or 'Unknown error'}"
        )
    elif source_info.status == StorageStatus.ERROR:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Source storage access error: {source_info.error_message or 'Path not accessible'}"
        )
    elif source_info.status == StorageStatus.WARNING:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=f"Source storage low on space: {source_info.free_space_gb:.1f}GB remaining"
        )
    elif source_info.status == StorageStatus.UNKNOWN:
        raise HTTPException(
            status_code=status.HTTP_202_ACCEPTED,
            detail="Source storage status being checked - please wait for monitoring to complete"
        )
    
    return source_info


@router.get("/storage/destination", response_model=StorageInfo)
async def get_destination_storage(
    storage_monitor: StorageMonitorService = Depends(get_storage_monitor)
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
    destination_info = storage_monitor.get_destination_info()
    
    if destination_info is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Destination storage information not available. Monitoring may not be started."
        )
    
    # Set HTTP status based on destination storage status
    if destination_info.status == StorageStatus.CRITICAL:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Critical destination storage issue: {destination_info.error_message or 'Unknown error'}"
        )
    elif destination_info.status == StorageStatus.ERROR:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Destination storage access error: {destination_info.error_message or 'Path not accessible'}"
        )
    elif destination_info.status == StorageStatus.WARNING:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=f"Destination storage low on space: {destination_info.free_space_gb:.1f}GB remaining"
        )
    elif destination_info.status == StorageStatus.UNKNOWN:
        raise HTTPException(
            status_code=status.HTTP_202_ACCEPTED,
            detail="Destination storage status being checked - please wait for monitoring to complete"
        )
    
    return destination_info

