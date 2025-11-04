"""
Ingest Monitor Service

Background service that monitors Just In Engine ingest channels using
dual polling loops: fast polling for recording status and slow polling
for error conditions.
"""
import asyncio
import logging
import httpx
from typing import Dict, List, Optional, Tuple

from app.config import Settings
from app.core.events.event_bus import DomainEventBus
from .models import ChannelState, JustInActiveChannels, JustInRecordingStatus, JustInErrors
from .events import (
    ChannelRecordingStartedEvent, 
    ChannelRecordingStoppedEvent,
    ChannelErrorDetectedEvent,
    ChannelSignalLostEvent,
    ChannelSignalRestoredEvent,
    IngestStatusUpdatedEvent
)


class IngestMonitorService:
    """
    Service responsible solely for monitoring Just In Engine channels
    and maintaining an in-memory cache of channel states.
    
    This class adheres to SRP by focusing only on data collection
    and event publishing related to ingest monitoring.
    """

    def __init__(self, settings: Settings, event_bus: DomainEventBus):
        self._settings = settings
        self._event_bus = event_bus
        self._client = httpx.AsyncClient(
            base_url=settings.justin_api_base_url, 
            timeout=settings.justin_api_timeout_seconds
        )
        self._status_cache: Dict[str, ChannelState] = {}
        self._running = False

        # Polling intervals from configuration
        self._fast_poll_interval = settings.justin_fast_poll_interval_seconds
        self._slow_poll_interval = settings.justin_slow_poll_interval_seconds

        # Task references for cleanup
        self._fast_loop_task: Optional[asyncio.Task] = None
        self._slow_loop_task: Optional[asyncio.Task] = None

    def get_status_cache(self) -> Dict[str, dict]:
        """
        Return a snapshot of the current cache for UI consumption.
        
        Returns the cache as simple dictionaries rather than Pydantic models
        to make it easy to serialize for WebSocket transmission.
        """
        return {name: state.model_dump() for name, state in self._status_cache.items()}

    async def start_monitoring(self) -> None:
        """Start the dual polling loops for ingest monitoring."""
        if self._running:
            logging.warning("IngestMonitorService is already running")
            return

        self._running = True
        logging.info("IngestMonitorService starting...")
        logging.info(f"Fast polling interval: {self._fast_poll_interval}s (recording status)")
        logging.info(f"Slow polling interval: {self._slow_poll_interval}s (error checking)")

        # Start both loops in parallel
        self._fast_loop_task = asyncio.create_task(self._fast_polling_loop())
        self._slow_loop_task = asyncio.create_task(self._slow_polling_loop())

        logging.info("IngestMonitorService monitoring loops started")

    async def stop_monitoring(self) -> None:
        """Stop all monitoring loops and cleanup resources."""
        if not self._running:
            logging.warning("IngestMonitorService is not running")
            return

        self._running = False
        logging.info("IngestMonitorService stop requested")

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

        # Close HTTP client
        await self._client.aclose()
        logging.info("IngestMonitorService stopped")

    async def _fast_polling_loop(self) -> None:
        """Fast polling loop - fetches recording status every 2 seconds."""
        while self._running:
            try:
                await self._fetch_all_channel_statuses()
                await asyncio.sleep(self._fast_poll_interval)
            except asyncio.CancelledError:
                logging.info("Fast polling loop cancelled")
                break
            except Exception as e:
                logging.error(f"Error in IngestMonitor fast_polling_loop: {e}")
                # Wait a bit before retrying on error
                await asyncio.sleep(5)

    async def _slow_polling_loop(self) -> None:
        """Slow polling loop - fetches error status every 30 seconds."""
        while self._running:
            try:
                await asyncio.sleep(self._slow_poll_interval)  # Wait first, then check
                if self._running:  # Check if still running after sleep
                    await self._fetch_all_channel_errors()
            except asyncio.CancelledError:
                logging.info("Slow polling loop cancelled")
                break
            except Exception as e:
                logging.error(f"Error in IngestMonitor slow_polling_loop: {e}")
                # Wait a bit before retrying on error
                await asyncio.sleep(10)

    async def _fetch_all_channel_statuses(self) -> None:
        """
        Fetch status for all channels in parallel (Fan-out/Fan-in pattern).
        
        This is the core of the fast polling loop that updates recording status.
        """
        try:
            # 1. Fetch the list of active channels
            response = await self._client.get("/ingest/activeChannels")
            response.raise_for_status()
            channel_data = JustInActiveChannels.model_validate(response.json())
            channel_names = channel_data.channel_names

            logging.debug(f"Found {len(channel_names)} active channels: {channel_names}")

            # 2. Create tasks to fetch status for each channel in parallel
            async with asyncio.TaskGroup() as tg:
                tasks = [
                    tg.create_task(self._fetch_single_channel_status(name)) 
                    for name in channel_names
                ]

            # 3. Collect results and update cache
            new_states: List[ChannelState] = [
                task.result() for task in tasks if task.result() is not None
            ]
            
            events_to_publish = self._update_cache_and_detect_changes(new_states)

            # 4. Publish individual change events
            for event in events_to_publish:
                await self._event_bus.publish(event)

            # 5. Always publish the complete snapshot for UI/Tally consumption
            await self._event_bus.publish(IngestStatusUpdatedEvent(
                status_snapshot=self.get_status_cache()
            ))

        except httpx.RequestError as e:
            logging.warning(f"Could not fetch activeChannels: {e}")
        except Exception as e:
            logging.error(f"Error in _fetch_all_channel_statuses: {e}")

    async def _fetch_single_channel_status(self, channel_name: str) -> Optional[ChannelState]:
        """Fetch recording status for a single channel."""
        try:
            # POST request with JSON payload as documented in justin.md
            payload = {"channel": channel_name}
            response = await self._client.post("/ingest/requestRecordingStatus", json=payload)
            response.raise_for_status()
            status_data = JustInRecordingStatus.model_validate(response.json())

            # Get existing state or create new one
            existing_state = self._status_cache.get(channel_name, ChannelState(name=channel_name))
            
            # Update the state with new data
            updated_state = ChannelState(
                name=channel_name,
                is_recording=status_data.rec,
                has_signal=status_data.options.TOAJustInEngineVideoSignalAvailable,
                has_errors=existing_state.has_errors,  # Preserve error state from slow loop
                last_errors=existing_state.last_errors,  # Preserve errors from slow loop
                frames=status_data.frames,
                hours=status_data.hours,
                minutes=status_data.minutes,
                seconds=status_data.seconds
            )

            return updated_state

        except Exception as e:
            logging.warning(f"Could not fetch status for {channel_name}: {e}")
            return None

    def _update_cache_and_detect_changes(self, new_states: List[ChannelState]) -> List:
        """
        Compare new states with cache and generate change events.
        
        This method implements the change detection logic for tally events.
        """
        events = []
        
        for new_state in new_states:
            channel_name = new_state.name
            old_state = self._status_cache.get(channel_name)

            # Detect recording status changes
            if old_state and old_state.is_recording != new_state.is_recording:
                if new_state.is_recording:
                    events.append(ChannelRecordingStartedEvent(channel_name=channel_name))
                    logging.info(f"Channel {channel_name} started recording")
                else:
                    events.append(ChannelRecordingStoppedEvent(channel_name=channel_name))
                    logging.info(f"Channel {channel_name} stopped recording")

            # Detect signal status changes
            if old_state and old_state.has_signal != new_state.has_signal:
                if new_state.has_signal:
                    events.append(ChannelSignalRestoredEvent(channel_name=channel_name))
                    logging.info(f"Channel {channel_name} signal restored")
                else:
                    events.append(ChannelSignalLostEvent(channel_name=channel_name))
                    logging.warning(f"Channel {channel_name} signal lost")

            # Update cache
            self._status_cache[channel_name] = new_state

        return events

    async def _fetch_all_channel_errors(self) -> None:
        """Fetch error status for all channels in parallel (slow polling loop)."""
        channel_names = list(self._status_cache.keys())
        if not channel_names:
            logging.debug("No channels to check for errors")
            return

        logging.debug(f"Checking errors for {len(channel_names)} channels")

        try:
            async with asyncio.TaskGroup() as tg:
                tasks = [
                    tg.create_task(self._fetch_single_channel_error(name)) 
                    for name in channel_names
                ]

            # Process results and update cache with error information
            for task in tasks:
                result = task.result()
                if result:
                    channel_name, errors, has_new_error = result
                    if channel_name in self._status_cache:
                        # Update the existing state with error information
                        current_state = self._status_cache[channel_name]
                        updated_state = ChannelState(
                            name=current_state.name,
                            is_recording=current_state.is_recording,
                            has_signal=current_state.has_signal,
                            has_errors=bool(errors),
                            last_errors=errors,
                            frames=current_state.frames,
                            hours=current_state.hours,
                            minutes=current_state.minutes,
                            seconds=current_state.seconds
                        )
                        self._status_cache[channel_name] = updated_state

                        # Publish error event if there's a new error
                        if has_new_error and errors:
                            await self._event_bus.publish(ChannelErrorDetectedEvent(
                                channel_name=channel_name,
                                error_message=errors[0].errorUIDescription,
                                error_code=errors[0].errorCode
                            ))
                            logging.warning(f"New error detected on {channel_name}: {errors[0].errorUIDescription}")

        except Exception as e:
            logging.error(f"Error in _fetch_all_channel_errors: {e}")

    async def _fetch_single_channel_error(self, channel_name: str) -> Optional[Tuple[str, List, bool]]:
        """Fetch errors for a single channel and detect if there are NEW errors."""
        try:
            # POST request with JSON payload as documented in justin.md
            payload = {"channel": channel_name, "clear": 0}
            response = await self._client.post("/ingest/errors", json=payload)
            response.raise_for_status()
            error_data = JustInErrors.model_validate(response.json())

            # Get old errors for comparison
            old_errors = self._status_cache.get(channel_name, ChannelState(name=channel_name)).last_errors
            
            # Simple check: is the newest error different from the old newest error?
            has_new_error = False
            if error_data.errors and (not old_errors or error_data.errors[0].date != old_errors[0].date):
                has_new_error = True

            return channel_name, error_data.errors, has_new_error

        except Exception as e:
            logging.warning(f"Could not fetch errors for {channel_name}: {e}")
            return None