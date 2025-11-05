"""
Ingest State Service

Håndterer den interne state-cache og change-detection logik for Just In Engine kanaler.
Denne klasse er ansvarlig for at vedligeholde kanalstatus og publicere events
når ændringer opdages.
"""
import logging
from typing import Dict, List, Tuple, Optional
from app.core.events.event_bus import DomainEventBus
from .models import ChannelState, JustInRecordingStatus, JustInError
from .events import (
    ChannelRecordingStartedEvent, 
    ChannelRecordingStoppedEvent,
    ChannelErrorDetectedEvent, 
    ChannelSignalLostEvent, 
    ChannelSignalRestoredEvent, 
    IngestStatusUpdatedEvent
)


class IngestStateService:
    """
    Håndterer den interne state-cache og change-detection logik.
    Publicerer events, når ændringer opdages.
    
    Denne klasse følger Single Responsibility Principle ved udelukkende
    at fokusere på state management og change detection.
    """

    def __init__(self, event_bus: DomainEventBus):
        """Initialize state service with event bus for publishing changes."""
        self._event_bus = event_bus
        self._status_cache: Dict[str, ChannelState] = {}
        logging.debug("IngestStateService initialized")

    def get_status_cache(self) -> Dict[str, dict]:
        """
        Returnerer et snapshot af cachen til UI'et.
        
        Returns:
            Dict[str, dict]: Cache som simple dictionaries til WebSocket serialization
        """
        return {name: state.model_dump() for name, state in self._status_cache.items()}

    def get_channel_names(self) -> List[str]:
        """
        Returnerer de kanaler, vi pt. kender til.
        
        Returns:
            List[str]: Liste af kanalnavne i cachen
        """
        return list(self._status_cache.keys())

    def add_new_channels(self, channel_names: List[str]) -> None:
        """
        Tilføjer nye kanaler til cachen, hvis de ikke allerede findes.
        
        Args:
            channel_names (List[str]): Liste af kanalnavne at tilføje
        """
        for channel_name in channel_names:
            if channel_name not in self._status_cache:
                self._status_cache[channel_name] = ChannelState(name=channel_name)
                logging.info(f"Added new channel to cache: {channel_name}")

    async def update_active_channels(self, channel_names: List[str]) -> None:
        """
        Opdaterer listen af aktive kanaler (async version af add_new_channels).
        
        Denne metode bruges af Worker til at opdatere aktive kanaler fra API.
        
        Args:
            channel_names (List[str]): Liste af aktive kanalnavne
        """
        self.add_new_channels(channel_names)
        logging.debug(f"Active channels updated: {len(channel_names)} channels: {channel_names}")

    async def update_channel_statuses(self, status_updates: List[Tuple[str, JustInRecordingStatus]]) -> None:
        """
        Opdaterer cachen med nye statusser og publicerer ændrings-events.
        
        Args:
            status_updates: Liste af (channel_name, status_data) tuples
        """
        events_to_publish = []

        for channel_name, status_data in status_updates:
            if channel_name not in self._status_cache:
                logging.warning(f"Channel {channel_name} not in cache, skipping status update")
                continue

            old_state = self._status_cache[channel_name]

            # Create new state with updated recording info, preserving error state
            new_state = ChannelState(
                name=channel_name,
                is_recording=status_data.rec,
                has_signal=status_data.options.TOAJustInEngineVideoSignalAvailable,
                has_errors=old_state.has_errors,  # Preserve from slow loop
                last_errors=old_state.last_errors,  # Preserve from slow loop
                frames=status_data.frames,
                hours=status_data.hours,
                minutes=status_data.minutes,
                seconds=status_data.seconds
            )

            # Detect changes and generate events
            events_to_publish.extend(self._detect_changes(old_state, new_state))
            
            # Update cache
            self._status_cache[channel_name] = new_state

        # Publish individual change events
        for event in events_to_publish:
            await self._event_bus.publish(event)

        # Always publish the complete snapshot for UI/Tally consumption
        await self._event_bus.publish(IngestStatusUpdatedEvent(
            status_snapshot=self.get_status_cache()
        ))

    def _detect_changes(self, old_state: ChannelState, new_state: ChannelState) -> List:
        """
        Sammenligner to states og returnerer en liste af events.
        
        Args:
            old_state (ChannelState): Tidligere tilstand
            new_state (ChannelState): Ny tilstand
            
        Returns:
            List: Liste af events der skal publiceres
        """
        events = []
        
        # Detect recording status changes
        if old_state.is_recording != new_state.is_recording:
            if new_state.is_recording:
                events.append(ChannelRecordingStartedEvent(channel_name=new_state.name))
                logging.info(f"Channel {new_state.name} started recording")
            else:
                events.append(ChannelRecordingStoppedEvent(channel_name=new_state.name))
                logging.info(f"Channel {new_state.name} stopped recording")

        # Detect signal status changes
        if old_state.has_signal != new_state.has_signal:
            if new_state.has_signal:
                events.append(ChannelSignalRestoredEvent(channel_name=new_state.name))
                logging.info(f"Channel {new_state.name} signal restored")
            else:
                events.append(ChannelSignalLostEvent(channel_name=new_state.name))
                logging.warning(f"Channel {new_state.name} signal lost")

        return events

    async def update_channel_errors(self, error_updates: List[Tuple[str, List[JustInError]]]) -> None:
        """
        Opdaterer cachen med nye fejl-lister og publicerer error events.
        
        Args:
            error_updates: Liste af (channel_name, errors) tuples
        """
        for channel_name, errors in error_updates:
            if channel_name not in self._status_cache:
                logging.warning(f"Channel {channel_name} not in cache, skipping error update")
                continue

            current_state = self._status_cache[channel_name]
            old_errors = current_state.last_errors

            # Check for NEW errors (simple comparison by date of first error)
            has_new_error = False
            if errors and (not old_errors or errors[0].date != old_errors[0].date):
                has_new_error = True

            # Update state with new error information
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

    def get_channel_state(self, channel_name: str) -> Optional[ChannelState]:
        """
        Henter specifik kanalstate fra cachen.
        
        Args:
            channel_name (str): Navn på kanalen
            
        Returns:
            Optional[ChannelState]: Kanalstate eller None hvis ikke fundet
        """
        return self._status_cache.get(channel_name)

    async def clear_all_errors(self) -> int:
        """
        Clear error state for all channels in cache.
        
        This is called after bulk clearing errors via API to update local state.
        
        Returns:
            int: Number of channels that had errors cleared
        """
        cleared_count = 0
        
        for channel_name, state in self._status_cache.items():
            if state.has_errors:
                # Update state to clear errors
                cleared_state = ChannelState(
                    name=state.name,
                    is_recording=state.is_recording,
                    has_signal=state.has_signal,
                    has_errors=False,  # Clear the error flag
                    last_errors=[],    # Clear the error list
                    frames=state.frames,
                    hours=state.hours,
                    minutes=state.minutes,
                    seconds=state.seconds
                )
                self._status_cache[channel_name] = cleared_state
                cleared_count += 1
                logging.info(f"Cleared error state for channel: {channel_name}")
        
        if cleared_count > 0:
            # Publish updated status to UI
            await self._event_bus.publish(IngestStatusUpdatedEvent(
                status_snapshot=self.get_status_cache()
            ))
            logging.info(f"Cleared error state for {cleared_count} channels")
        
        return cleared_count

    def clear_cache(self) -> None:
        """Ryd hele cachen (nyttigt til testing)."""
        self._status_cache.clear()
        logging.info("Channel status cache cleared")