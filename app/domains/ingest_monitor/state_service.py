"""
Ingest State Service

Håndterer den interne state-cache og change-detection logik for Just In Engine kanaler.
Denne klasse er ansvarlig for at vedligeholde kanalstatus og publicere events
når ændringer opdages.
"""
import logging
from typing import Dict, List, Tuple, Optional
from app.core.events.event_bus import DomainEventBus
from app.core.events.domain_event import DomainEvent
from .models import ChannelState, JustInRecordingStatus, JustInError
from .events import (
    ChannelRecordingStartedEvent, 
    ChannelRecordingStoppedEvent,
    ChannelErrorDetectedEvent, 
    ChannelSignalLostEvent, 
    ChannelSignalRestoredEvent, 
    IngestStatusUpdatedEvent,
    IngestOnlineEvent,
    IngestOfflineEvent,
    RecordingPathsDiscoveredEvent,
    AutoStopWarningEvent,
    AutoStopTriggeredEvent,
)


class IngestStateService:
    """
    Håndterer den interne state-cache og change-detection logik.
    Publicerer events, når ændringer opdages.
    
    Denne klasse følger Single Responsibility Principle ved udelukkende
    at fokusere på state management og change detection.
    """

    def __init__(
        self,
        event_bus: DomainEventBus,
        auto_stop_minutes: int = 0,
        auto_stop_warning_minutes: int = 5,
    ):
        """Initialize state service with event bus for publishing changes.

        Args:
            event_bus: Event bus for publishing domain events.
            auto_stop_minutes: Stop all channels after N minutes (0 = disabled).
            auto_stop_warning_minutes: Warn N minutes before auto-stop limit.
        """
        self._event_bus = event_bus
        self._status_cache: Dict[str, ChannelState] = {}
        self._is_connected: bool = False # Track connection status
        self._recording_paths: Dict[str, List[str]] = {}  # channel -> [paths]
        self._recording_preset_names: Dict[str, str] = {}  # channel -> preset_name

        # Auto-stop configuration
        self._auto_stop_warning_minutes_raw: int = auto_stop_warning_minutes
        self._auto_stop_limit_seconds: int = auto_stop_minutes * 60
        self._auto_stop_warning_seconds: int = (
            (auto_stop_minutes - auto_stop_warning_minutes) * 60
            if auto_stop_minutes > auto_stop_warning_minutes
            else 0
        )
        # Guard flags - reset when all recording stops
        self._auto_stop_warning_sent: bool = False
        self._auto_stop_triggered: bool = False

        if self._auto_stop_limit_seconds > 0:
            logging.info(
                "Auto-stop enabled: limit=%dm, warning at=%dm before",
                auto_stop_minutes,
                auto_stop_warning_minutes,
            )
        logging.debug("IngestStateService initialized")

    def update_auto_stop(self, auto_stop_minutes: int) -> None:
        """Update auto-stop limit at runtime (0 = disabled)."""
        warning = self._auto_stop_warning_minutes_raw
        self._auto_stop_limit_seconds = auto_stop_minutes * 60
        self._auto_stop_warning_seconds = (
            (auto_stop_minutes - warning) * 60
            if auto_stop_minutes > warning
            else 0
        )
        # Reset guards so a new cycle can fire
        self._auto_stop_warning_sent = False
        self._auto_stop_triggered = False
        logging.info("Auto-stop updated: limit=%dm", auto_stop_minutes)

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

    def is_connected(self) -> bool:
        """
        Check if ingest monitor is currently connected to Just In Engine.
        
        Returns:
            bool: True if connected, False if disconnected
        """
        return self._is_connected

    async def set_connection_status(self, is_connected: bool) -> None:
        """
        Update the connection status and publish events on changes.
        
        Args:
            is_connected (bool): True if connected, False if disconnected
        """
        if self._is_connected != is_connected:
            self._is_connected = is_connected
            if is_connected:
                logging.info(" Ingest monitor connected to Just In Engine")
                await self._event_bus.publish(IngestOnlineEvent())
            else:
                logging.warning(" Ingest monitor disconnected from Just In Engine")
                await self._event_bus.publish(IngestOfflineEvent())

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

    async def update_active_channels(self, channel_names: Optional[List[str]]) -> None:
        """
        Opdaterer listen af aktive kanaler (async version af add_new_channels).
        
        Denne metode bruges af Worker til at opdatere aktive kanaler fra API.
        Tilfojer nye kanaler og fjerner kanaler der ikke laengere er aktive.
        
        Args:
            channel_names: Liste af kanalnavne eller None ved API fejl
        """
        if channel_names is None:
            return

        active_set = set(channel_names)
        current_set = set(self._status_cache.keys())

        # Remove channels that are no longer active
        removed = current_set - active_set
        for name in removed:
            del self._status_cache[name]
            logging.info(f"Removed inactive channel from cache: {name}")

        # Add new channels
        self.add_new_channels(channel_names)

        if removed:
            logging.info(f"Active channels updated: added {len(active_set - current_set)}, removed {len(removed)}, total {len(self._status_cache)}")
        else:
            logging.debug(f"Active channels updated: {len(channel_names)} channels: {channel_names}")

    async def update_channel_statuses(self, status_updates: Optional[List[Tuple[str, JustInRecordingStatus]]]) -> None:
        """
        Opdaterer cachen med nye statusser og publicerer ændrings-events.
        
        Args:
            status_updates: Liste af (channel_name, status_data) tuples eller None ved API fejl
        """
        if status_updates is None:
            logging.debug("Skipping status update due to API failure")
            return
            
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
                has_errors=old_state.has_errors, # Preserve from slow loop
                last_errors=old_state.last_errors, # Preserve from slow loop
                frames=status_data.frames,
                hours=status_data.hours,
                minutes=status_data.minutes,
                seconds=status_data.seconds,
                start_timecode_frames=status_data.options.TOAJustInEngineStartTimecodeFrames,
                framerate=status_data.options.TOAJustInEngineFramerate,
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
            status_snapshot=self.get_status_cache(),
            auto_stop_info=self.get_auto_stop_info(),
        ))

        # Auto-stop detection (after all statuses updated)
        await self._check_auto_stop()

    def _detect_changes(self, old_state: ChannelState, new_state: ChannelState) -> List:
        """
        Sammenligner to states og returnerer en liste af events.
        
        Args:
            old_state (ChannelState): Tidligere tilstand
            new_state (ChannelState): Ny tilstand
            
        Returns:
            List: Liste af events der skal publiceres
        """
        events: list[DomainEvent] = []
        
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

    # ── Auto-stop detection ──────────────────────────────────────────────

    @staticmethod
    def _channel_recording_seconds(state: ChannelState) -> int:
        """Calculate recording duration in seconds from Justin's timecodes.

        Justin reports the current *wall-clock* timecode, not the duration.
        Duration = (current_timecode_frames - start_timecode_frames) / fps.

        Returns 0 when data is missing or start_timecode_frames is 0
        (Justin reports 0 for idle channels — treat as "not yet available").
        """
        if not state.is_recording:
            return 0

        framerate_raw = state.framerate  # e.g. 2500 = 25.00 fps
        start_frames = state.start_timecode_frames

        if not framerate_raw or framerate_raw <= 0:
            return 0

        # Justin reports StartTimecodeFrames=0 for idle/stopped channels.
        # If we see 0 while rec=true, the data is stale or transitioning.
        if start_frames is None or start_frames <= 0:
            logging.debug(
                "Channel %s: start_timecode_frames=%s (idle marker) — "
                "duration unknown, returning 0",
                state.name,
                start_frames,
            )
            return 0

        fps = framerate_raw / 100

        current_total_frames = (
            ((state.hours or 0) * 3600 + (state.minutes or 0) * 60 + (state.seconds or 0))
            * fps
            + (state.frames or 0)
        )

        duration_frames = current_total_frames - start_frames

        # Handle midnight wraparound (start ~23:59, now ~00:01)
        if duration_frames < 0:
            duration_frames += 24 * 3600 * fps

        return int(duration_frames / fps)

    async def _check_auto_stop(self) -> None:
        """
        Check if any recording channel has exceeded the auto-stop limit.

        Uses Justin's own timecodes (authoritative) - no local timers.
        Guard flags prevent repeated events; they reset when all recording stops.
        """
        if self._auto_stop_limit_seconds <= 0:
            return  # Feature disabled

        recording_channels = [
            s for s in self._status_cache.values() if s.is_recording
        ]

        # Reset guards when nobody is recording
        if not recording_channels:
            if self._auto_stop_warning_sent or self._auto_stop_triggered:
                self._auto_stop_warning_sent = False
                self._auto_stop_triggered = False
                logging.debug("Auto-stop guards reset (no channels recording)")
            return

        # Find channel with the longest recording time
        longest = max(recording_channels, key=self._channel_recording_seconds)
        longest_seconds = self._channel_recording_seconds(longest)

        # Check trigger (limit reached)
        if not self._auto_stop_triggered and longest_seconds >= self._auto_stop_limit_seconds:
            self._auto_stop_triggered = True
            self._auto_stop_warning_sent = True  # No need for warning anymore
            logging.warning(
                "AUTO-STOP triggered by %s at %ds (limit=%ds)",
                longest.name,
                longest_seconds,
                self._auto_stop_limit_seconds,
            )
            await self._event_bus.publish(
                AutoStopTriggeredEvent(
                    channel_name=longest.name,
                    recording_seconds=longest_seconds,
                    limit_seconds=self._auto_stop_limit_seconds,
                )
            )
            return

        # Check warning (approaching limit)
        if (
            not self._auto_stop_warning_sent
            and self._auto_stop_warning_seconds > 0
            and longest_seconds >= self._auto_stop_warning_seconds
        ):
            self._auto_stop_warning_sent = True
            remaining = self._auto_stop_limit_seconds - longest_seconds
            logging.info(
                "AUTO-STOP warning: %s at %ds, %ds remaining (limit=%ds)",
                longest.name,
                longest_seconds,
                remaining,
                self._auto_stop_limit_seconds,
            )
            await self._event_bus.publish(
                AutoStopWarningEvent(
                    channel_name=longest.name,
                    recording_seconds=longest_seconds,
                    limit_seconds=self._auto_stop_limit_seconds,
                    remaining_seconds=remaining,
                )
            )

    def get_auto_stop_info(self) -> dict:
        """
        Return auto-stop status for UI consumption.

        Returns:
            Dict with enabled, limit_seconds, warning_sent, triggered,
            and max_recording_seconds across all recording channels.
        """
        recording_channels = [
            s for s in self._status_cache.values() if s.is_recording
        ]
        max_rec = (
            max(self._channel_recording_seconds(c) for c in recording_channels)
            if recording_channels
            else 0
        )
        return {
            "enabled": self._auto_stop_limit_seconds > 0,
            "limit_seconds": self._auto_stop_limit_seconds,
            "warning_seconds": self._auto_stop_warning_seconds,
            "warning_sent": self._auto_stop_warning_sent,
            "triggered": self._auto_stop_triggered,
            "max_recording_seconds": max_rec,
            "remaining_seconds": max(self._auto_stop_limit_seconds - max_rec, 0)
            if self._auto_stop_limit_seconds > 0
            else 0,
        }

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
                seconds=current_state.seconds,
                start_timecode_frames=current_state.start_timecode_frames,
                framerate=current_state.framerate,
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
                    has_errors=False, # Clear the error flag
                    last_errors=[],    # Clear the error list
                    frames=state.frames,
                    hours=state.hours,
                    minutes=state.minutes,
                    seconds=state.seconds,
                    start_timecode_frames=state.start_timecode_frames,
                    framerate=state.framerate,
                )
                self._status_cache[channel_name] = cleared_state
                cleared_count += 1
                logging.info(f"Cleared error state for channel: {channel_name}")
        
        if cleared_count > 0:
            # Publish updated status to UI
            await self._event_bus.publish(IngestStatusUpdatedEvent(
                status_snapshot=self.get_status_cache(),
                auto_stop_info=self.get_auto_stop_info(),
            ))
            logging.info(f"Cleared error state for {cleared_count} channels")
        
        return cleared_count

    async def update_recording_paths(
        self,
        channel_name: str,
        paths: List[str],
        preset_name: str,
    ) -> bool:
        """
        Opdater cached recording-paths for en kanal.
        Publicerer RecordingPathsDiscoveredEvent ved aendringer.

        Returns:
            True hvis der var en aendring (event publiceret), ellers False.
        """
        old_paths = self._recording_paths.get(channel_name, [])
        old_preset = self._recording_preset_names.get(channel_name, "")

        changed = old_paths != paths or old_preset != preset_name
        if not changed:
            return False

        self._recording_paths[channel_name] = paths
        self._recording_preset_names[channel_name] = preset_name

        await self._event_bus.publish(
            RecordingPathsDiscoveredEvent(
                paths=tuple(paths),
                preset_name=preset_name,
                channel_name=channel_name,
            )
        )
        logging.info(
            "Recording paths updated for %s (preset=%s): %s",
            channel_name,
            preset_name,
            paths,
        )
        return True

    def get_recording_paths(self) -> Dict[str, dict]:
        """
        Returnerer et snapshot af alle opdagede recording-paths.

        Returns:
            Dict med channel_name -> {preset_name, paths} til UI.
        """
        result: Dict[str, dict] = {}
        for channel_name, paths in self._recording_paths.items():
            result[channel_name] = {
                "preset_name": self._recording_preset_names.get(channel_name, ""),
                "paths": paths,
            }
        return result

    def clear_cache(self) -> None:
        """Ryd hele cachen (nyttigt til testing)."""
        self._status_cache.clear()
        self._recording_paths.clear()
        self._recording_preset_names.clear()
        logging.info("Channel status cache cleared")