"""
Auto-Stop Event Handler

Listens for AutoStopTriggeredEvent and stops all channels on Just In Engine.
Follows SRP: its only job is to execute the stop action when the threshold
is reached. Detection happens in StateService, this handler only acts.
"""
import logging

from .api_client import IngestApiClient
from .events import AutoStopTriggeredEvent


class AutoStopHandler:
    """
    Stops all Just In Engine channels when the auto-stop limit is reached.

    This is intentionally a thin handler - StateService owns the detection
    logic, and this class only performs the side-effect (API call).
    """

    def __init__(self, api_client: IngestApiClient):
        self._api_client = api_client

    async def handle_auto_stop_triggered(self, event: AutoStopTriggeredEvent) -> None:
        """Stop all channels when auto-stop limit is reached."""
        logging.warning(
            "AUTO-STOP: Stopping all channels. "
            "Channel %s reached %ds (limit=%ds)",
            event.channel_name,
            event.recording_seconds,
            event.limit_seconds,
        )

        channel_names = await self._api_client.get_active_channels()
        if not channel_names:
            logging.error("AUTO-STOP: Could not get active channels to stop")
            return

        stopped = 0
        for name in channel_names:
            success = await self._api_client.stop_channel(name)
            if success:
                stopped += 1
            else:
                logging.error("AUTO-STOP: Failed to stop channel %s", name)

        logging.warning(
            "AUTO-STOP: Stopped %d/%d channels",
            stopped,
            len(channel_names),
        )
