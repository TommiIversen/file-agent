"""
Query handlers for storage monitoring operations.
Handles read-only operations for storage status information.
"""
from fastapi import HTTPException, status

from app.models import StorageInfo, StorageStatus
from app.dependencies.storage import get_storage_monitor
from app.domains.shared.queries.storage_queries import (
    GetSourceStorageQuery,
    GetDestinationStorageQuery
)


class StorageQueryHandler:
    """Handler for storage monitoring query operations."""
    
    def __init__(self):
        # Use dependency injection to get the storage monitor
        pass
    
    async def handle_get_source_storage(self, query: GetSourceStorageQuery) -> StorageInfo:
        """
        Get source storage information.
        
        Args:
            query: GetSourceStorageQuery
            
        Returns:
            StorageInfo for source directory
            
        Raises:
            HTTPException: With appropriate status codes based on storage status
        """
        storage_monitor = get_storage_monitor()
        source_info = storage_monitor.get_source_info()

        if source_info is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Source storage information not available. Monitoring may not be started.",
            )
        if source_info.status == StorageStatus.CRITICAL:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Critical source storage issue: {source_info.error_message or 'Unknown error'}",
            )
        elif source_info.status == StorageStatus.ERROR:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Source storage access error: {source_info.error_message or 'Path not accessible'}",
            )
        elif source_info.status == StorageStatus.WARNING:
            raise HTTPException(
                status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
                detail=f"Source storage low on space: {source_info.free_space_gb:.1f}GB remaining",
            )

        return source_info
    
    async def handle_get_destination_storage(self, query: GetDestinationStorageQuery) -> StorageInfo:
        """
        Get destination storage information.
        
        Args:
            query: GetDestinationStorageQuery
            
        Returns:
            StorageInfo for destination directory
            
        Raises:
            HTTPException: With appropriate status codes based on storage status
        """
        storage_monitor = get_storage_monitor()
        destination_info = storage_monitor.get_destination_info()

        if destination_info is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Destination storage information not available. Monitoring may not be started.",
            )

        # Set HTTP status based on destination storage status
        if destination_info.status == StorageStatus.CRITICAL:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Critical destination storage issue: {destination_info.error_message or 'Unknown error'}",
            )
        elif destination_info.status == StorageStatus.ERROR:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Destination storage access error: {destination_info.error_message or 'Path not accessible'}",
            )
        elif destination_info.status == StorageStatus.WARNING:
            raise HTTPException(
                status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
                detail=f"Destination storage low on space: {destination_info.free_space_gb:.1f}GB remaining",
            )

        return destination_info