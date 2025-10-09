"""
Storage API Endpoints for File Transfer Agent.

REST API endpoints for storage monitoring with appropriate HTTP status codes.
Provides external monitoring capabilities and health check integration.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, status
from datetime import datetime

from ..dependencies import get_storage_monitor
from ..services.storage_monitor import StorageMonitorService
from ..models import StorageInfo, StorageStatus
from pydantic import BaseModel


# Response models
class StorageResponse(BaseModel):
    """Complete storage overview response"""
    source: Optional[StorageInfo]
    destination: Optional[StorageInfo]
    overall_status: StorageStatus
    last_updated: datetime
    monitoring_active: bool


class StorageHealthResponse(BaseModel):
    """Health check response with storage status"""
    status: str
    storage_status: StorageStatus
    details: dict


router = APIRouter(prefix="/api", tags=["storage"])


@router.get("/storage", response_model=StorageResponse)
async def get_storage_overview(
    storage_monitor: StorageMonitorService = Depends(get_storage_monitor)
) -> StorageResponse:
    """
    Get complete storage overview for both source and destination.
    
    Returns:
        StorageResponse with both source and destination info
        
    HTTP Status Codes:
        200: Normal operation (all OK or WARNING)
        507: Insufficient Storage (WARNING threshold exceeded)
        503: Service Unavailable (ERROR or CRITICAL status)
    """
    source_info = storage_monitor.get_source_info()
    destination_info = storage_monitor.get_destination_info()
    overall_status = storage_monitor.get_overall_status()
    monitoring_status = storage_monitor.get_monitoring_status()
    
    response = StorageResponse(
        source=source_info,
        destination=destination_info,
        overall_status=overall_status,
        last_updated=datetime.now(),
        monitoring_active=monitoring_status["is_running"]
    )
    
    # Set appropriate HTTP status code based on storage status
    if overall_status == StorageStatus.CRITICAL:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Critical storage issues detected"
        )
    elif overall_status == StorageStatus.ERROR:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage access errors detected"
        )
    elif overall_status == StorageStatus.WARNING:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail="Storage space warnings detected"
        )
    
    # Status OK - return 200
    return response


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
    
    # Set HTTP status based on source storage status
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
    
    return destination_info


@router.get("/storage/health", response_model=StorageHealthResponse)
async def get_storage_health(
    storage_monitor: StorageMonitorService = Depends(get_storage_monitor)
) -> StorageHealthResponse:
    """
    Get storage health status for monitoring systems.
    
    Simplified endpoint for external health checks and monitoring tools.
    Always returns 200 OK but includes status in response body.
    
    Returns:
        StorageHealthResponse with overall health status
    """
    overall_status = storage_monitor.get_overall_status()
    monitoring_status = storage_monitor.get_monitoring_status()
    source_info = storage_monitor.get_source_info()
    destination_info = storage_monitor.get_destination_info()
    
    # Create health status string
    if overall_status == StorageStatus.OK:
        health_status = "healthy"
    elif overall_status == StorageStatus.WARNING:
        health_status = "warning"
    elif overall_status == StorageStatus.ERROR:
        health_status = "error"
    else:  # CRITICAL
        health_status = "critical"
    
    # Build details dictionary
    details = {
        "monitoring_active": monitoring_status["is_running"],
        "check_interval_seconds": monitoring_status["check_interval_seconds"],
        "source_status": source_info.status.value if source_info else "unknown",
        "destination_status": destination_info.status.value if destination_info else "unknown"
    }
    
    # Add space details if available
    if source_info:
        details["source_free_gb"] = round(source_info.free_space_gb, 2)
        details["source_total_gb"] = round(source_info.total_space_gb, 2)
    
    if destination_info:
        details["destination_free_gb"] = round(destination_info.free_space_gb, 2)
        details["destination_total_gb"] = round(destination_info.total_space_gb, 2)
    
    return StorageHealthResponse(
        status=health_status,
        storage_status=overall_status,
        details=details
    )


# Additional utility endpoints for advanced monitoring

@router.get("/storage/thresholds")
async def get_storage_thresholds(
    storage_monitor: StorageMonitorService = Depends(get_storage_monitor)
) -> dict:
    """
    Get configured storage thresholds.
    
    Returns:
        Dictionary with current threshold configuration
    """
    monitoring_status = storage_monitor.get_monitoring_status()
    
    # Get thresholds from current storage info
    source_info = storage_monitor.get_source_info()
    destination_info = storage_monitor.get_destination_info()
    
    thresholds = {
        "monitoring_active": monitoring_status["is_running"],
        "check_interval_seconds": monitoring_status["check_interval_seconds"]
    }
    
    if source_info:
        thresholds["source"] = {
            "warning_threshold_gb": source_info.warning_threshold_gb,
            "critical_threshold_gb": source_info.critical_threshold_gb
        }
    
    if destination_info:
        thresholds["destination"] = {
            "warning_threshold_gb": destination_info.warning_threshold_gb,
            "critical_threshold_gb": destination_info.critical_threshold_gb
        }
    
    return thresholds