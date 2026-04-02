"""
Ingest Monitor Command Handlers
"""
import logging
from typing import Dict, Any
from app.core.cqrs.command import CommandHandler
from .commands import ClearAllChannelErrorsCommand, StartAllChannelsCommand, StopAllChannelsCommand


class ClearAllChannelErrorsCommandHandler(CommandHandler[ClearAllChannelErrorsCommand, Dict[str, Any]]):
    """Handler for ClearAllChannelErrorsCommand that clears errors on all channels."""

    def __init__(self, ingest_monitor_worker):
        self._worker = ingest_monitor_worker

    async def handle(self, command: ClearAllChannelErrorsCommand) -> Dict[str, Any]:
        try:
            channel_names = self._worker._state_service.get_channel_names()

            if not channel_names:
                return {
                    "success": False,
                    "channels_cleared": 0,
                    "total_channels": 0,
                    "message": "No channels found to clear errors for",
                }

            cleared_count = await self._worker._api_client.clear_all_channel_errors(channel_names)
            await self._worker._state_service.clear_all_errors()

            return {
                "success": True,
                "channels_cleared": cleared_count,
                "total_channels": len(channel_names),
                "message": f"Successfully cleared errors for {cleared_count}/{len(channel_names)} channels",
            }

        except Exception as e:
            logging.error(f"Error clearing all channel errors: {e}", exc_info=True)
            return {
                "success": False,
                "channels_cleared": 0,
                "total_channels": 0,
                "message": f"Failed to clear errors: {str(e)}",
            }


class StartAllChannelsCommandHandler(CommandHandler[StartAllChannelsCommand, Dict[str, Any]]):
    """Handler for StartAllChannelsCommand that starts all channels."""

    def __init__(self, ingest_monitor_worker):
        self._worker = ingest_monitor_worker

    async def handle(self, command: StartAllChannelsCommand) -> Dict[str, Any]:
        try:
            channel_names = self._worker._state_service.get_channel_names()

            if not channel_names:
                return {
                    "success": False,
                    "channels_started": 0,
                    "total_channels": 0,
                    "message": "No channels found to start",
                }

            started_count = await self._worker._api_client.start_all_channels(channel_names)

            return {
                "success": True,
                "channels_started": started_count,
                "total_channels": len(channel_names),
                "message": f"Successfully started {started_count}/{len(channel_names)} channels",
            }

        except Exception as e:
            logging.error(f"Error starting all channels: {e}", exc_info=True)
            return {
                "success": False,
                "channels_started": 0,
                "total_channels": 0,
                "message": f"Failed to start channels: {str(e)}",
            }


class StopAllChannelsCommandHandler(CommandHandler[StopAllChannelsCommand, Dict[str, Any]]):
    """Handler for StopAllChannelsCommand that stops all channels."""

    def __init__(self, ingest_monitor_worker):
        self._worker = ingest_monitor_worker

    async def handle(self, command: StopAllChannelsCommand) -> Dict[str, Any]:
        try:
            channel_names = self._worker._state_service.get_channel_names()

            if not channel_names:
                return {
                    "success": False,
                    "channels_stopped": 0,
                    "total_channels": 0,
                    "message": "No channels found to stop",
                }

            stopped_count = await self._worker._api_client.stop_all_channels(channel_names)

            return {
                "success": True,
                "channels_stopped": stopped_count,
                "total_channels": len(channel_names),
                "message": f"Successfully stopped {stopped_count}/{len(channel_names)} channels",
            }

        except Exception as e:
            logging.error(f"Error stopping all channels: {e}", exc_info=True)
            return {
                "success": False,
                "channels_stopped": 0,
                "total_channels": 0,
                "message": f"Failed to stop channels: {str(e)}",
            }
