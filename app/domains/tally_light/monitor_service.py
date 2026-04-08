"""
Tally Switch Monitor Service

Background service that periodically checks tally switch connectivity 
and publishes status updates via WebSocket.
"""
import asyncio
import logging
from typing import Optional, Dict, Any
from datetime import datetime

from app.core.events.event_bus import DomainEventBus
from .protocols import PowerSwitchProtocol
from .models import TallySwitchStatus
from .events import TallySwitchOnlineEvent, TallySwitchOfflineEvent, TallySwitchStatusUpdatedEvent


class TallySwitchMonitorService:
    """
    Background service for monitoring tally switch connectivity.
    
    Periodically checks if the configured tally switch is reachable
    and publishes status updates through the event system.
    """

    def __init__(
        self, 
        switch_client: PowerSwitchProtocol, 
        ip_address: str,
        event_bus: DomainEventBus,
        check_interval_seconds: int = 30
    ):
        """
        Initialize the monitor service.
        
        Args:
            switch_client: The power switch client to monitor
            ip_address: IP address for identification in events
            event_bus: Event bus for publishing status updates
            check_interval_seconds: How often to check (default: 30 seconds)
        """
        self._switch_client = switch_client
        self._ip_address = ip_address
        self._event_bus = event_bus
        self._check_interval = check_interval_seconds
        
        # State tracking
        self._current_status: Optional[TallySwitchStatus] = None
        self._monitoring_task: Optional[asyncio.Task] = None
        self._is_running = False
        
        logging.info(f"TallySwitchMonitorService initialized for {ip_address} (check interval: {check_interval_seconds}s)")

    def update_ip(self, ip_address: str) -> None:
        """Update the monitored IP address (used for event metadata)."""
        self._ip_address = ip_address

    @property
    def current_status(self) -> Optional[TallySwitchStatus]:
        """Get the current status of the tally switch."""
        return self._current_status

    @property
    def is_monitoring(self) -> bool:
        """Check if monitoring is currently active."""
        return self._is_running

    async def start_monitoring(self) -> None:
        """Start the background monitoring task."""
        if self._is_running:
            logging.warning("Tally switch monitoring is already running")
            return

        self._is_running = True
        self._monitoring_task = asyncio.create_task(self._monitor_loop())
        logging.info(f"Started tally switch monitoring for {self._ip_address}")

    async def stop_monitoring(self) -> None:
        """Stop the background monitoring task."""
        if not self._is_running:
            return

        self._is_running = False
        
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
            self._monitoring_task = None

        logging.info(f"Stopped tally switch monitoring for {self._ip_address}")

    async def check_status_now(self) -> TallySwitchStatus:
        """
        Perform an immediate status check.
        
        Returns:
            TallySwitchStatus: Current status
        """
        return await self._perform_status_check()

    async def _monitor_loop(self) -> None:
        """Main monitoring loop that runs in the background."""
        try:
            while self._is_running:
                try:
                    # Perform status check
                    await self._perform_status_check()
                    
                    # Wait for next check
                    await asyncio.sleep(self._check_interval)
                    
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logging.error(f"Error in tally switch monitor loop: {e}", exc_info=True)
                    # Continue monitoring even if one check fails
                    await asyncio.sleep(self._check_interval)
                    
        except Exception as e:
            logging.error(f"Fatal error in tally switch monitor loop: {e}", exc_info=True)
        finally:
            self._is_running = False

    async def _perform_status_check(self) -> TallySwitchStatus:
        """
        Perform a single status check and publish events if status changed.
        """
        previous_status = self._current_status
        
        try:
            # Check if switch is online
            is_online = await self._switch_client.is_online()
            
            # Create new status
            new_status = TallySwitchStatus(
                is_online=is_online,
                switch_type=self._switch_client.switch_type.value,
                ip_address=self._ip_address,
                last_checked=datetime.now(),
                error_message=None
            )
            
            logging.debug(f"Tally switch {self._ip_address} status: {'ONLINE' if is_online else 'OFFLINE'}")
            
        except Exception as e:
            # Create status with error
            new_status = TallySwitchStatus(
                is_online=False,
                switch_type=self._switch_client.switch_type.value,
                ip_address=self._ip_address,
                last_checked=datetime.now(),
                error_message=str(e)
            )
            
            logging.warning(f"Error checking tally switch {self._ip_address}: {e}")

        # Update current status
        self._current_status = new_status
        
        # Publish events
        await self._publish_status_events(new_status, previous_status)
        
        return new_status

    async def _publish_status_events(
        self, 
        new_status: TallySwitchStatus, 
        previous_status: Optional[TallySwitchStatus]
    ) -> None:
        """Publish appropriate events based on status changes."""
        try:
            # Always publish general status update
            status_event = TallySwitchStatusUpdatedEvent(status=new_status, previous_status=previous_status)
            await self._event_bus.publish(status_event)
            
            # Publish specific online/offline events if status changed
            if previous_status is None or previous_status.is_online != new_status.is_online:
                if new_status.is_online:
                    online_event = TallySwitchOnlineEvent(status=new_status)
                    await self._event_bus.publish(online_event)
                    logging.info(f" Tally switch {self._ip_address} came ONLINE")
                else:
                    offline_event = TallySwitchOfflineEvent(status=new_status)
                    await self._event_bus.publish(offline_event)
                    logging.warning(f" Tally switch {self._ip_address} went OFFLINE")
            
        except Exception as e:
            logging.error(f"Error publishing tally switch events: {e}", exc_info=True)

    def get_status_dict(self) -> Dict[str, Any]:
        """
        Get current status as a dictionary for API responses.
        
        Returns:
            Dict with status information suitable for JSON serialization
        """
        if self._current_status is None:
            return {
                "is_online": None,
                "switch_type": self._switch_client.switch_type.value,
                "ip_address": self._ip_address,
                "last_checked": None,
                "error_message": "Not yet checked",
                "is_monitoring": self._is_running
            }
        
        return {
            "is_online": self._current_status.is_online,
            "switch_type": self._current_status.switch_type,
            "ip_address": self._current_status.ip_address,
            "last_checked": self._current_status.last_checked.isoformat(),
            "error_message": self._current_status.error_message,
            "is_monitoring": self._is_running
        }