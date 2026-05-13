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
from .session_tracker import RecordingSessionTracker
from .events import (
    ChannelRecordingStartedEvent, 
    ChannelRecordingStoppedEvent,
    ChannelErrorDetectedEvent, 
    ChannelSignalLostEvent, 
    ChannelSignalRestoredEvent, 
    IngestStatusUpdatedEvent,
    IngestOnlineEvent,
    IngestOfflineEvent,
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
        session_tracker: RecordingSessionTracker | None = None,
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
        self._seen_error_dates: Dict[str, set] = {}  # channel -> set of error dates

        # Segment-split tracking: accumulate duration across Justin file splits.
        # When Justin splits a recording (e.g. every 30 min), it resets
        # StartTimecodeFrames.  We detect this and accumulate previous segments.
        self._cumulative_seconds: Dict[str, int] = {}  # channel -> accumulated seconds from completed segments
        self._last_start_frames: Dict[str, Optional[int]] = {}  # channel -> last known start TC

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

        # Recording session tracking
        self._session_tracker = session_tracker

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

            # Segment-split detection: if channel is still recording but
            # StartTimecodeFrames changed, Justin has split to a new file.
            # Accumulate the *previous* segment's duration before updating cache.
            self._track_segment_split(channel_name, old_state, new_state)

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

        # Update session tracker on recording changes
        if self._session_tracker and old_state.is_recording != new_state.is_recording:
            if new_state.is_recording:
                self._session_tracker.handle_channel_started(new_state.name)
            else:
                # Determine which channels are still recording
                active_recording = {
                    name
                    for name, state in self._status_cache.items()
                    if state.is_recording and name != new_state.name
                }
                self._session_tracker.handle_channel_stopped(
                    new_state.name, active_recording
                )

        return events

    # ── Segment-split tracking ───────────────────────────────────────────

    def _track_segment_split(
        self,
        channel_name: str,
        old_state: ChannelState,
        new_state: ChannelState,
    ) -> None:
        """Detect Justin file-splits and accumulate previous segment duration.

        When Justin splits a recording (e.g. every 30 min) it resets
        ``StartTimecodeFrames``.  If a channel is still recording but its
        start-TC changed, the old segment's duration is added to the
        cumulative counter so auto-stop tracks total recording time.

        When a channel stops recording, the accumulator is reset.
        """
        new_start = new_state.start_timecode_frames
        was_recording = old_state.is_recording
        is_recording = new_state.is_recording

        if not is_recording:
            # Recording stopped → reset accumulator for next session
            self._cumulative_seconds.pop(channel_name, None)
            self._last_start_frames.pop(channel_name, None)
            return

        last_known = self._last_start_frames.get(channel_name)

        if not was_recording:
            # Fresh recording start → initialise tracker, no accumulation
            self._cumulative_seconds[channel_name] = 0
            self._last_start_frames[channel_name] = new_start
            return

        # Still recording — check for segment split
        if (
            last_known is not None
            and new_start is not None
            and new_start > 0
            and last_known > 0
            and new_start != last_known
        ):
            # Start-TC changed while still recording → segment split.
            # Compute previous segment duration from the two start-TCs:
            # new_start is where Justin began the new file, i.e. the split
            # point — so (new_start - last_known) = previous segment length.
            # This is more robust than using old_state's TC, which could be
            # stale (e.g. during a transient start_frames=0 transition).
            fps = (new_state.framerate or 2500) / 100
            split_frames = new_start - last_known
            # Handle midnight wraparound
            if split_frames < 0:
                split_frames += int(24 * 3600 * fps)
            prev_segment = int(split_frames / fps)
            self._cumulative_seconds[channel_name] = (
                self._cumulative_seconds.get(channel_name, 0) + prev_segment
            )
            logging.info(
                "Segment split detected on %s: prev segment %ds, "
                "cumulative %ds (new start_frames=%s)",
                channel_name,
                prev_segment,
                self._cumulative_seconds[channel_name],
                new_start,
            )

        # Only update last_start_frames with valid values to survive
        # transient start_frames=0 that Justin may report during a split.
        if new_start is not None and new_start > 0:
            self._last_start_frames[channel_name] = new_start

    def _total_recording_seconds(self, state: ChannelState) -> int:
        """Current segment duration + accumulated previous segments."""
        current = self._channel_recording_seconds(state)
        cumulative = self._cumulative_seconds.get(state.name, 0)
        return cumulative + current

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

        # Find channel with the longest recording time (including
        # accumulated duration from previous Justin file-split segments).
        longest = max(recording_channels, key=self._total_recording_seconds)
        longest_seconds = self._total_recording_seconds(longest)

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
            max(self._total_recording_seconds(c) for c in recording_channels)
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
        
        Tracks individual errors by their date field to avoid duplicate
        event publishing across polling cycles.
        
        Args:
            error_updates: Liste af (channel_name, errors) tuples
        """
        for channel_name, errors in error_updates:
            if channel_name not in self._status_cache:
                logging.warning(f"Channel {channel_name} not in cache, skipping error update")
                continue

            current_state = self._status_cache[channel_name]

            # Identify genuinely new errors using per-channel seen set
            seen = self._seen_error_dates.setdefault(channel_name, set())
            new_errors = [e for e in errors if e.date not in seen]

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

            # Mark new errors as seen and aggregate by type to avoid log spam
            for error in new_errors:
                seen.add(error.date)

            # Publish ONE event per unique error type (not per individual error)
            if new_errors:
                from collections import Counter
                error_counts = Counter(e.errorUIDescription for e in new_errors)
                for error_msg, count in error_counts.items():
                    # Pick the first error of this type for metadata
                    representative = next(e for e in new_errors if e.errorUIDescription == error_msg)
                    description = None
                    if representative.errorUserInfo and representative.errorUserInfo.NSLocalizedDescription:
                        description = representative.errorUserInfo.NSLocalizedDescription
                    await self._event_bus.publish(ChannelErrorDetectedEvent(
                        channel_name=channel_name,
                        error_message=representative.errorUIDescription,
                        error_code=representative.errorCode,
                        error_domain=representative.errorDomain,
                        error_description=description,
                        error_type=representative.errorType,
                    ))
                    if count > 1:
                        logging.warning(f"New errors on {channel_name}: {error_msg} (x{count})")
                    else:
                        logging.warning(f"New error on {channel_name}: {error_msg}")

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
        
        # Reset seen-error tracking so re-appearing errors are detected
        self._seen_error_dates.clear()

        if cleared_count > 0:
            # Publish updated status to UI
            await self._event_bus.publish(IngestStatusUpdatedEvent(
                status_snapshot=self.get_status_cache(),
                auto_stop_info=self.get_auto_stop_info(),
            ))
            logging.info(f"Cleared error state for {cleared_count} channels")
        
        return cleared_count

    def clear_cache(self) -> None:
        """Ryd hele cachen (nyttigt til testing)."""
        self._status_cache.clear()
        logging.info("Channel status cache cleared")