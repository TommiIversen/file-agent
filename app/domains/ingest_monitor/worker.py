"""
Ingest Monitor Worker

Ren worker-klasse der orkestrerer polling-loops og dataflow mellem
IngestApiClient og IngestStateService. Følger Single Responsibility
Principle ved kun at fokusere på polling og orchestration.
"""
import asyncio
import logging
from typing import Optional
from app.config import Settings
from .api_client import IngestApiClient
from .state_service import IngestStateService


class IngestMonitorWorker:
    """
    Ren worker-klasse. Dens ENESTE ansvar er at køre
    polling-loops og orkestrere dataflowet mellem
    ApiClient og StateService.
    
    Denne klasse følger Single Responsibility Principle ved
    kun at håndtere polling orchestration.
    """

    def __init__(
        self, 
        settings: Settings, 
        api_client: IngestApiClient, 
        state_service: IngestStateService
    ):
        """Initialize worker with injected dependencies."""
        self._settings = settings
        self._api_client = api_client
        self._state_service = state_service
        self._running = False

        # Polling intervals from configuration
        self._fast_poll_interval = settings.justin_fast_poll_interval_seconds
        self._slow_poll_interval = settings.justin_slow_poll_interval_seconds

        # Task references for cleanup
        self._fast_loop_task: Optional[asyncio.Task] = None
        self._slow_loop_task: Optional[asyncio.Task] = None
        
        logging.info("IngestMonitorWorker initialized")

    def get_status_cache(self) -> dict:
        """
        Delegate cache access to StateService.
        
        Returns:
            dict: Current channel status cache
        """
        return self._state_service.get_status_cache()
    
    def get_connection_status(self) -> bool:
        """
        Get the current connection status.
        
        Returns:
            bool: True if connected to Just In Engine, False otherwise
        """
        return self._state_service.is_connected()

    def get_recording_paths(self) -> dict:
        """
        Delegate recording-path access to StateService.

        Returns:
            dict: channel_name -> {preset_name, paths}
        """
        return self._state_service.get_recording_paths()

    async def start_monitoring(self) -> None:
        """Start the dual polling loops for ingest monitoring."""
        if self._running:
            logging.warning("IngestMonitorWorker is already running")
            return

        self._running = True
        logging.info("IngestMonitorWorker starting...")
        logging.info(f"Fast polling interval: {self._fast_poll_interval}s (recording status)")
        logging.info(f"Slow polling interval: {self._slow_poll_interval}s (active channels + error checking)")

        # Initialize active channels before starting loops via StateService
        await self._state_service.update_active_channels(
            await self._api_client.get_active_channels()
        )

        # Start both loops in parallel
        self._fast_loop_task = asyncio.create_task(self._fast_polling_loop())
        self._slow_loop_task = asyncio.create_task(self._slow_polling_loop())

        logging.info("IngestMonitorWorker monitoring loops started")

    async def stop_monitoring(self) -> None:
        """Stop all monitoring loops and cleanup resources."""
        if not self._running:
            logging.warning("IngestMonitorWorker is not running")
            return

        self._running = False
        logging.info("IngestMonitorWorker stop requested")

        # Cancel both tasks
        if self._fast_loop_task and not self._fast_loop_task.done():
            self._fast_loop_task.cancel()
            try:
                await self._fast_loop_task
            except asyncio.CancelledError:
                logging.debug("Fast polling task cancelled successfully")

        if self._slow_loop_task and not self._slow_loop_task.done():
            self._slow_loop_task.cancel()
            try:
                await self._slow_loop_task
            except asyncio.CancelledError:
                logging.debug("Slow polling task cancelled successfully")

        # Close API client
        await self._api_client.close()
        logging.info("IngestMonitorWorker stopped")

    async def _fast_polling_loop(self) -> None:
        """Fast polling loop - orchestrates channel status fetching via StateService."""
        while self._running:
            try:
                # Get current channel names from StateService cache
                channel_names = list(self._state_service.get_status_cache().keys())
                if not channel_names:
                    logging.debug("No channels in cache, skipping fast poll")
                    await asyncio.sleep(self._fast_poll_interval)
                    continue

                logging.debug(f"Polling {len(channel_names)} cached channels: {channel_names}")

                # Fetch all channel statuses via API client
                all_statuses = await self._api_client.get_all_channel_statuses(channel_names)
                
                # Set connection status and update state in one block
                if all_statuses is not None:
                    await self._state_service.set_connection_status(True)
                    await self._state_service.update_channel_statuses(all_statuses)
                else:
                    await self._state_service.set_connection_status(False)

                await asyncio.sleep(self._fast_poll_interval)
            except asyncio.CancelledError:
                logging.info("Fast polling loop cancelled")
                break
            except Exception as e:
                logging.error(f"Error in IngestMonitor fast_polling_loop: {e}", exc_info=True)
                # Mark as disconnected on API errors
                await self._state_service.set_connection_status(False)
                # Wait a bit before retrying on error
                await asyncio.sleep(5)

    async def _discover_all_recording_paths(self, channel_names: list[str]) -> None:
        """Discover recording paths for each active channel."""
        for ch_name in channel_names:
            try:
                result = await self._api_client.discover_recording_paths(ch_name)
                if result is not None:
                    paths, preset_name = result
                    await self._state_service.update_recording_paths(
                        channel_name=ch_name,
                        paths=paths,
                        preset_name=preset_name,
                    )
            except Exception as e:
                logging.debug(
                    "Could not discover recording paths for %s: %s",
                    ch_name,
                    e,
                )

    async def _slow_polling_loop(self) -> None:
        """Slow polling loop - orchestrates active channels and error checking."""
        while self._running:
            try:
                await asyncio.sleep(self._slow_poll_interval) # Wait first, then check
                if not self._running:
                    break

                # Update active channels via API client and StateService
                active_channels = await self._api_client.get_active_channels()

                # Set connection status based on API success
                if active_channels is not None:  # Empty list is valid, None indicates failure
                    await self._state_service.set_connection_status(True)
                    await self._state_service.update_active_channels(active_channels)
                else:
                    await self._state_service.set_connection_status(False)

                # Get current channel names for error checking
                channel_names = list(self._state_service.get_status_cache().keys())
                if channel_names:
                    # Fetch errors for all channels
                    all_errors = await self._api_client.get_all_channel_errors(channel_names)
                    await self._state_service.update_channel_errors(all_errors)

                # Discover recording paths (extracted for testability)
                await self._discover_all_recording_paths(channel_names)

            except asyncio.CancelledError:
                logging.info("Slow polling loop cancelled")
                break
            except Exception as e:
                logging.error(f"Error in IngestMonitor slow_polling_loop: {e}", exc_info=True)
                # Mark as disconnected on API errors
                await self._state_service.set_connection_status(False)
                # Wait a bit before retrying on error
                await asyncio.sleep(10)

