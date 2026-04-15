"""GlobalEventLogger - Event logging for UI visibility with SQLite persistence.

En singleton service der abonnerer på kritiske domæne-events og
persisterer dem til SQLite. Alle reads går direkte til databasen.
"""
import logging
from typing import List, Optional
from datetime import datetime
from dataclasses import dataclass

from app.core.events.domain_event import DomainEvent
from app.core.events.file_events import (
    FileStatusChangedEvent,
    FileCopyFailedEvent,
)
from app.core.events.storage_events import (
    NetworkFailureDetectedEvent,
    DestinationUnavailableEvent,
    DestinationRecoveredEvent,
    NetworkStatusChanged,
    StorageStatusChangedEvent,
    MountStatusChangedEvent,
)
from app.core.events.scanner_events import ScannerStatusChangedEvent
from app.core.events.ingest_events import ChannelErrorDetectedEvent
from app.core.events.audio_events import (
    AudioRecordingStartedEvent,
    AudioRecordingStoppedEvent,
    AudioRecordingErrorEvent,
    AudioDeviceDisconnectedEvent,
    AudioOverflowWarningEvent,
)
from app.models import FileStatus, StorageStatus, MountStatus

# TYPE_CHECKING avoids circular import — SqliteEventStore only used for type hints
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.core.sqlite_event_store import SqliteEventStore


@dataclass
class LoggedEvent:
    """En simpel datastruktur til at holde UI-venlige logbeskeder."""
    timestamp: datetime
    event_type: str
    message: str
    level: str # INFO, WARNING, ERROR
    context: Optional[dict] = None # Extra context data
    id: Optional[int] = None # DB primary key, used for cursor pagination

    def to_dict(self):
        result = {
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "message": self.message,
            "level": self.level,
        }
        if self.context:
            result["context"] = self.context
        return result


class GlobalEventLogger:
    """
    Event logger der abonnerer på kritiske domæne-events, persisterer dem
    til SQLite og gør dem tilgængelige for UI'et.
    
    Writes: event → SQLite (via SqliteEventStore)
    Reads: alle queries går direkte til SQLite
    """
    
    def __init__(self):
        self._event_store: Optional["SqliteEventStore"] = None
        logging.info("GlobalEventLogger initialiseret.")

    def set_event_store(self, store: Optional["SqliteEventStore"]) -> None:
        """Attach or detach a persistent event store."""
        self._event_store = store
        if store is not None:
            logging.info("GlobalEventLogger: SQLite event store attached")
        else:
            logging.info("GlobalEventLogger: SQLite event store detached")

    async def register_with_event_bus(self, event_bus):
        """
        Registrerer alle event handlers med event bus'en.
        Denne metode skal kaldes under app startup.
        """
        await event_bus.subscribe(NetworkFailureDetectedEvent, self.handle_network_failure_detected)
        await event_bus.subscribe(DestinationUnavailableEvent, self.handle_destination_unavailable)
        await event_bus.subscribe(DestinationRecoveredEvent, self.handle_destination_recovered)
        await event_bus.subscribe(NetworkStatusChanged, self.handle_network_status_changed)
        await event_bus.subscribe(FileStatusChangedEvent, self.handle_file_status_changed)
        await event_bus.subscribe(FileCopyFailedEvent, self.handle_file_copy_failed)
        await event_bus.subscribe(StorageStatusChangedEvent, self.handle_storage_status_changed)
        await event_bus.subscribe(MountStatusChangedEvent, self.handle_mount_status_changed)
        await event_bus.subscribe(ScannerStatusChangedEvent, self.handle_scanner_status_changed)
        await event_bus.subscribe(ChannelErrorDetectedEvent, self.handle_channel_error_detected)
        await event_bus.subscribe(AudioRecordingStartedEvent, self.handle_audio_recording_started)
        await event_bus.subscribe(AudioRecordingStoppedEvent, self.handle_audio_recording_stopped)
        await event_bus.subscribe(AudioRecordingErrorEvent, self.handle_audio_recording_error)
        await event_bus.subscribe(AudioDeviceDisconnectedEvent, self.handle_audio_device_disconnected)
        await event_bus.subscribe(AudioOverflowWarningEvent, self.handle_audio_overflow_warning)
        
        logging.info("GlobalEventLogger: Alle event handlers registreret med event bus")

    async def _add_log(
        self, 
        event: DomainEvent, 
        message: str, 
        level: str, 
        context: Optional[dict] = None
    ):
        """Persist a new event to SQLite."""
        log_entry = LoggedEvent(
            timestamp=event.timestamp,
            event_type=type(event).__name__,
            message=message,
            level=level,
            context=context
        )

        if self._event_store is not None:
            try:
                await self._event_store.add_event(log_entry)
            except Exception:
                logging.error("Failed to persist event to SQLite", exc_info=True)

    async def get_events(
        self,
        limit: Optional[int] = None,
        level: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        before_id: Optional[int] = None,
    ) -> List[LoggedEvent]:
        """
        Query events from SQLite with optional filters.
        
        Returns newest-first. All reads go to the database.
        """
        if self._event_store is None:
            return []
        return await self._event_store.get_events(
            limit=limit, level=level, from_date=from_date, to_date=to_date, before_id=before_id
        )

    # --- Event Handlers (Disse kaldes af EventBus) ---

    async def handle_destination_unavailable(self, event: DestinationUnavailableEvent):
        await self._add_log(
            event, 
            f"Destination utilgængelig: {event.reason}", 
            "ERROR",
            {"reason": event.reason}
        )

    async def handle_destination_recovered(self, event: DestinationRecoveredEvent):
        await self._add_log(
            event, 
            f"Destination recovered: {event.reason}", 
            "INFO",
            {"reason": event.reason}
        )

    async def handle_network_status_changed(self, event: NetworkStatusChanged):
        if not event.available:
            await self._add_log(
                event, 
                f"Netværk nede: {event.reason} (kilde: {event.source})", 
                "ERROR",
                {"source": event.source, "reason": event.reason}
            )
        else:
            await self._add_log(
                event, 
                f"Netværk recovered: {event.reason} (kilde: {event.source})", 
                "INFO",
                {"source": event.source, "reason": event.reason}
            )

    async def handle_network_failure_detected(self, event: NetworkFailureDetectedEvent):
        await self._add_log(
            event, 
            f"Netværksfejl under kopiering: {event.error_message}", 
            "ERROR",
            {
                "file_id": event.file_id,
                "operation": event.operation,
                "error": event.error_message
            }
        )

    async def handle_file_copy_failed(self, event: FileCopyFailedEvent):
        await self._add_log(
            event, 
            f"Filkopiering fejlede: {event.error_message}", 
            "WARNING",
            {
                "file_path": event.file_path,
                "error": event.error_message
            }
        )

    async def handle_file_status_changed(self, event: FileStatusChangedEvent):
        """Log status transitions to failed/error states."""
        if event.new_status in [FileStatus.FAILED, FileStatus.SPACE_ERROR]:
            old_status_str = event.old_status.value if event.old_status else "unknown"
            context = {
                "file_path": event.file_path,
                "old_status": old_status_str,
                "new_status": event.new_status.value
            }
            if event.error_message:
                context["reason"] = event.error_message
            await self._add_log(
                event, 
                f"Fil status: {event.file_path} → {event.new_status.value}", 
                "WARNING",
                context
            )

    async def handle_storage_status_changed(self, event: StorageStatusChangedEvent):
        update = event.update
        level = "INFO" if update.new_status == StorageStatus.OK else "WARNING"
        
        await self._add_log(
            event, 
            f"Storage status: {update.storage_info.path} → {update.new_status.value}", 
            level,
            {
                "storage_type": update.storage_type,
                "old_status": update.old_status.value if update.old_status else None,
                "new_status": update.new_status.value,
                "location": update.storage_info.path,
                "free_space": f"{update.storage_info.free_space_gb:.1f} GB" if update.storage_info.free_space_gb else "unknown",
                "total_space": f"{update.storage_info.total_space_gb:.1f} GB" if update.storage_info.total_space_gb else "unknown"
            }
        )

    async def handle_mount_status_changed(self, event: MountStatusChangedEvent):
        update = event.update
        if update.mount_status == MountStatus.SUCCESS:
            level = "INFO"
        elif update.mount_status == MountStatus.ATTEMPTING:
            level = "INFO"
        else:
            level = "ERROR"
        
        await self._add_log(
            event, 
            f"Mount status: {update.storage_type} → {update.mount_status.value}", 
            level,
            {
                "storage_type": update.storage_type,
                "mount_status": update.mount_status.value,
                "share_url": update.share_url,
                "mount_path": update.mount_path
            }
        )

    async def handle_scanner_status_changed(self, event: ScannerStatusChangedEvent):
        status_text = "started" if event.is_scanning else "stopped"
        await self._add_log(
            event, 
            f"File scanner {status_text}", 
            "INFO",
            {
                "is_active": event.is_scanning,
            }
        )

    async def handle_channel_error_detected(self, event: ChannelErrorDetectedEvent):
        context: dict = {
            "channel_name": event.channel_name,
            "error_code": event.error_code,
            "error_message": event.error_message,
        }
        if event.error_domain:
            context["error_domain"] = event.error_domain
        if event.error_description:
            context["error_description"] = event.error_description
        if event.error_type is not None:
            context["error_type"] = event.error_type
        await self._add_log(
            event,
            f"Ingest error on {event.channel_name}: {event.error_message}",
            "WARNING",
            context,
        )

    async def handle_generic_event(self, event: DomainEvent):
        """Generic handler for events not specifically handled above."""
        await self._add_log(
            event,
            f"System event: {type(event).__name__}",
            "INFO"
        )

    async def handle_audio_recording_started(self, event: AudioRecordingStartedEvent):
        await self._add_log(
            event,
            f"Audio recording started: {len(event.tracks)} tracks @ {event.samplerate}Hz",
            "INFO",
            {"session_id": event.session_id, "tracks": event.tracks},
        )

    async def handle_audio_recording_stopped(self, event: AudioRecordingStoppedEvent):
        await self._add_log(
            event,
            f"Audio recording stopped after {event.duration_seconds:.1f}s ({len(event.files)} files)",
            "INFO",
            {"session_id": event.session_id, "overflow_count": event.overflow_count},
        )

    async def handle_audio_recording_error(self, event: AudioRecordingErrorEvent):
        await self._add_log(
            event,
            f"Audio recording error: {event.error}",
            "ERROR" if not event.recoverable else "WARNING",
            {"recoverable": event.recoverable, "session_id": event.session_id},
        )

    async def handle_audio_device_disconnected(self, event: AudioDeviceDisconnectedEvent):
        await self._add_log(
            event,
            f"Audio device disconnected: {event.device_name}",
            "ERROR",
            {"device_name": event.device_name},
        )

    async def handle_audio_overflow_warning(self, event: AudioOverflowWarningEvent):
        await self._add_log(
            event,
            f"Audio buffer overflow: {event.dropped_count} blocks dropped (total: {event.total_drops})",
            "WARNING",
            {"dropped_count": event.dropped_count, "total_drops": event.total_drops, "session_id": event.session_id},
        )
