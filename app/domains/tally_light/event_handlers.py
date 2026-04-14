"""
Tally Light Domain Event Handlers

Handles power switch tally light control based on ingest status.
Manages three states: OFF, SOLID ON, and BLINKING.
"""
import asyncio
import logging
from enum import Enum
from typing import Optional

from app.config import Settings
from app.core.events.ingest_events import IngestStatusUpdatedEvent, AutoStopWarningEvent
from .protocols import PowerSwitchError, PowerSwitchConnectionError
from .factory import create_power_switch


class TallyState(Enum):
    """Defines the 3 desired states for the shared Tally light."""
    OFF = "off"
    SOLID_ON = "on"
    BLINKING = "blink"


class TallyLightEventHandler:
    """
    Manages the shared Tally light by starting/stopping a
    background blinker task based on overall recording status.
    
    This class adheres to SRP by focusing solely on tally light
    control logic and state management.
    """

    def __init__(self, settings: Settings):
        self._power_switch = create_power_switch(settings)
        self._current_tally_state: TallyState = TallyState.OFF
        self._blinker_task: Optional[asyncio.Task] = None
        self._blink_interval_sec: float = settings.tally_light_blink_interval_seconds
        self._lock = asyncio.Lock() # Protects access to _blinker_task
        self._auto_stop_warning_active: bool = False  # Set by AutoStopWarningEvent
        
        logging.info("TallyLightEventHandler initialized with software blinker logic")
        logging.info(f"Power switch type: {self._power_switch.switch_type.value}")
        logging.info(f"Switch IP: {settings.tally_light_switch_ip}")
        logging.info(f"Blink interval: {self._blink_interval_sec}s")

    async def handle_ingest_status_update(self, event: IngestStatusUpdatedEvent) -> None:
        """
        Receives the complete status snapshot every 2 seconds
        and updates the Tally light state accordingly.
        
        State logic:
        - No channels recording → OFF
        - All channels recording → SOLID ON  
        - Some channels recording → BLINKING
        
        Note: When an auto-stop warning is active the tally is forced
        to BLINKING via the separate handle_auto_stop_warning handler,
        which takes precedence until the warning phase ends.
        """
        # If auto-stop warning is active, the warning handler owns the state
        # (unless nobody is recording anymore — then reset the flag)
        if self._auto_stop_warning_active:
            recording_count = sum(
                1 for state in (event.status_snapshot or {}).values()
                if state.get("is_recording", False)
            )
            if recording_count == 0:
                self._auto_stop_warning_active = False
                logging.info("Auto-stop warning flag cleared (no channels recording)")
            else:
                return

        snapshot = event.status_snapshot

        # 1. Determine the desired new state
        new_state: TallyState
        if not snapshot:
            new_state = TallyState.OFF
        else:
            total_channels = len(snapshot)
            recording_channels = sum(
                1 for state in snapshot.values() if state.get("is_recording", False)
            )

            if recording_channels == 0:
                new_state = TallyState.OFF
            elif recording_channels == total_channels:
                new_state = TallyState.SOLID_ON # All channels recording
            else:
                new_state = TallyState.BLINKING # At least one, but not all, recording

        # 2. Apply the change only if it's new
        if new_state != self._current_tally_state:
            await self._update_tally_state(
                new_state, 
                f"{recording_channels}/{total_channels} channels recording"
            )

    async def handle_auto_stop_warning(self, event: AutoStopWarningEvent) -> None:
        """
        Force the tally light to BLINKING when an auto-stop warning fires.
        
        This overrides the normal recording-based logic until all recording
        stops (which resets the warning flag in StateService).
        """
        self._auto_stop_warning_active = True
        remaining_min = event.remaining_seconds // 60
        await self._update_tally_state(
            TallyState.BLINKING,
            f"Auto-stop warning: {remaining_min}m remaining (channel {event.channel_name})"
        )

    async def _update_tally_state(self, new_state: TallyState, reason: str) -> None:
        """
        Handles the transition between OFF, SOLID_ON, and BLINKING
        by managing the blinker task.
        """
        async with self._lock:
            if new_state == self._current_tally_state:
                return # Another event managed to change it in the meantime

            current_state_str = self._current_tally_state.value
            new_state_str = new_state.value
            logging.info(f"Tally state changed: {current_state_str} → {new_state_str} (Reason: {reason})")

            # 1. Always stop the old blinker task (if running)
            if self._blinker_task and not self._blinker_task.done():
                self._blinker_task.cancel()
                try:
                    await self._blinker_task # Wait for it to shutdown and turn off light
                except asyncio.CancelledError:
                    pass # Expected
            self._blinker_task = None

            # 2. Set the new state
            try:
                if new_state == TallyState.SOLID_ON:
                    await self._power_switch.turn_on()
                    logging.info("Tally light set to SOLID ON")
                elif new_state == TallyState.OFF:
                    await self._power_switch.turn_off()
                    logging.info("Tally light set to OFF")
                elif new_state == TallyState.BLINKING:
                    # Start the new blinker task in background
                    self._blinker_task = asyncio.create_task(self._blinker_loop())
                    logging.info("Tally light set to BLINKING")

                self._current_tally_state = new_state # Store the new state

            except PowerSwitchConnectionError as e:
                # Switch is offline/unreachable — expected when tally lamp is off
                logging.warning(f"Tally switch unreachable (wanted {new_state_str}): {e}")
                # We don't update _current_tally_state, so it will try again on next event

            except PowerSwitchError as e:
                logging.error(f"Could not update tally light to {new_state_str}: {e}", exc_info=True)
                # We don't update _current_tally_state, so it will try again on next event

    async def _blinker_loop(self) -> None:
        """
        Infinite loop that turns the light on/off via power switch protocol.
        
        This method runs as a background task and handles its own cancellation.
        """
        try:
            while True:
                try:
                    await self._power_switch.turn_on()
                except PowerSwitchConnectionError:
                    pass  # Switch offline — already logged as WARNING in client
                await asyncio.sleep(self._blink_interval_sec)
                try:
                    await self._power_switch.turn_off()
                except PowerSwitchConnectionError:
                    pass  # Switch offline — already logged as WARNING in client
                await asyncio.sleep(self._blink_interval_sec)
        except asyncio.CancelledError:
            # Important cleanup: Make sure to turn off the light when blink stops
            try:
                await self._power_switch.turn_off()
                logging.info("Blinker task stopped, light turned off")
            except PowerSwitchError as e:
                logging.warning(f"Could not turn off tally light during blink stop: {e}")
            raise # Re-raise CancelledError
        except Exception as e:
            logging.error(f"Error in blinker loop: {e}", exc_info=True)
            # Reset state to OFF so it can be restarted
            self._current_tally_state = TallyState.OFF

    async def stop_worker(self) -> None:
        """
        Called from main.py lifespan to ensure clean shutdown.
        
        This method ensures the tally light is turned off when the
        application shuts down.
        """
        logging.info("Stopping TallyLightEventHandler (turning off light)...")
        await self._update_tally_state(TallyState.OFF, "Application shutting down")
        await self._power_switch.close()
        logging.info("TallyLightEventHandler stopped")

    def get_current_state(self) -> TallyState:
        """Get the current tally light state for debugging/monitoring."""
        return self._current_tally_state

    def is_blinking(self) -> bool:
        """Check if the tally light is currently blinking."""
        return (self._current_tally_state == TallyState.BLINKING and 
                self._blinker_task is not None and 
                not self._blinker_task.done())