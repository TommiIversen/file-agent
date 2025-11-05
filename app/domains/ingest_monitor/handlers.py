"""
Ingest Monitor CQRS Handlers

This module contains both query and command handlers for ingest monitor operations
following the CQRS pattern.
"""

from typing import Dict, Any
from app.core.cqrs.query import QueryHandler
from app.core.cqrs.command import CommandHandler
from .queries import GetIngestStatusQuery
from .commands import ClearAllChannelErrorsCommand


class GetIngestStatusQueryHandler(QueryHandler[GetIngestStatusQuery, Dict[str, Any]]):
    """
    Handler for GetIngestStatusQuery that retrieves cached channel status data.
    
    This handler adheres to SRP by focusing solely on data retrieval
    from the IngestMonitorWorker cache via delegation to StateService.
    """

    def __init__(self, ingest_monitor_worker):
        self._worker = ingest_monitor_worker

    async def handle(self, query: GetIngestStatusQuery) -> Dict[str, Any]:
        """
        Handle the query by returning the current cached status.
        
        Returns the complete status snapshot directly from the worker's cache.
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
        return self._worker.get_status_cache()


class ClearAllChannelErrorsCommandHandler(CommandHandler[ClearAllChannelErrorsCommand, Dict[str, Any]]):
    """
    Handler for ClearAllChannelErrorsCommand that clears errors on all channels.
    
    This handler orchestrates the clear operation across API and state services.
    """

    def __init__(self, ingest_monitor_worker):
        self._worker = ingest_monitor_worker

    async def handle(self, command: ClearAllChannelErrorsCommand) -> Dict[str, Any]:
        """
        Handle the command by clearing errors on all channels.
        
        Args:
            command: The ClearAllChannelErrorsCommand
            
        Returns:
            Dict with operation result:
            {
                "success": true,
                "channels_cleared": 5,
                "total_channels": 5,
                "message": "Successfully cleared errors for 5 channels"
            }
        """
        try:
            # Get current channel names from state service
            channel_names = self._worker._state_service.get_channel_names()
            
            if not channel_names:
                return {
                    "success": False,
                    "channels_cleared": 0,
                    "total_channels": 0,
                    "message": "No channels found to clear errors for"
                }

            # Clear errors via API client
            cleared_count = await self._worker._api_client.clear_all_channel_errors(channel_names)
            
            # Update local state to reflect cleared errors
            await self._worker._state_service.clear_all_errors()
            
            return {
                "success": True,
                "channels_cleared": cleared_count,
                "total_channels": len(channel_names),
                "message": f"Successfully cleared errors for {cleared_count}/{len(channel_names)} channels"
            }
            
        except Exception as e:
            import logging
            logging.error(f"Error clearing all channel errors: {e}")
            return {
                "success": False,
                "channels_cleared": 0,
                "total_channels": 0,
                "message": f"Failed to clear errors: {str(e)}"
            }