"""
Ingest Monitor Query Handlers

This module contains query handlers for retrieving ingest monitor data
following the CQRS pattern.
"""

from typing import Dict, Any
from app.core.cqrs.query import QueryHandler
from .queries import GetIngestStatusQuery
from .service import IngestMonitorService


class GetIngestStatusQueryHandler(QueryHandler[GetIngestStatusQuery, Dict[str, Any]]):
    """
    Handler for GetIngestStatusQuery that retrieves cached channel status data.
    
    This handler adheres to SRP by focusing solely on data retrieval
    from the IngestMonitorService cache.
    """

    def __init__(self, ingest_monitor_service: IngestMonitorService):
        self._service = ingest_monitor_service

    async def handle(self, query: GetIngestStatusQuery) -> Dict[str, Any]:
        """
        Handle the query by returning the current cached status.
        
        Returns the complete status snapshot directly from the service cache.
        This is lightning-fast since it's just an in-memory dictionary access.
        
        Args:
            query: The GetIngestStatusQuery (no parameters needed)
            
        Returns:
            Dict containing channel statuses in the format:
            {
                "KAM_1": {
                    "name": "KAM_1",
                    "is_recording": true,
                    "has_signal": true,
                    "has_errors": false,
                    "frames": 11,
                    "hours": 0,
                    "minutes": 24,
                    "seconds": 47
                },
                ...
            }
        """
        return self._service.get_status_cache()