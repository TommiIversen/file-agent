"""
GlobalEventLogger - In-memory event logging for UI visibility 📊

En singleton service der abonnerer på kritiske domæne-events og gemmer dem
i en in-memory deque for UI'et at forespørge.
"""
import logging
import asyncio
from collections import deque
from typing import List, Deque, Optional
from datetime import datetime
from dataclasses import dataclass

from app.core.events.domain_event import DomainEvent


@dataclass
class LoggedEvent:
    """En simpel datastruktur til at holde UI-venlige logbeskeder."""
    timestamp: datetime
    event_type: str
    message: str
    level: str  # INFO, WARNING, ERROR
    context: Optional[dict] = None  # Extra context data

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
    En in-memory log, der abonnerer på kritiske domæne-events
    og gør dem tilgængelige for UI'et.
    
    Implementeret som thread-safe singleton med automatisk cleanup.
    """
    
    def __init__(self, max_size: int = 200):
        # En 'deque' er en liste, der automatisk fjerner de ældste
        # elementer, når den bliver fuld. Perfekt til en in-memory log.
        self.max_size = max_size
        self._events: Deque[LoggedEvent] = deque(maxlen=max_size)
        self._lock = asyncio.Lock()
        logging.info(f"GlobalEventLogger initialiseret med plads til {max_size} events.")

    async def register_with_event_bus(self, event_bus):
        """
        Registrerer alle event handlers med event bus'en.
        Denne metode skal kaldes under app startup.
        """
        # Import locally to avoid circular dependencies
        from app.core.events.storage_events import (
            NetworkFailureDetectedEvent, DestinationUnavailableEvent, 
            DestinationRecoveredEvent, NetworkStatusChanged,
            StorageStatusChangedEvent, MountStatusChangedEvent
        )
        from app.core.events.file_events import FileStatusChangedEvent
        from app.core.events.scanner_events import ScannerStatusChangedEvent
        
        # Register all our event handlers
        await event_bus.subscribe(NetworkFailureDetectedEvent, self.handle_network_failure_detected)
        await event_bus.subscribe(DestinationUnavailableEvent, self.handle_destination_unavailable)
        await event_bus.subscribe(DestinationRecoveredEvent, self.handle_destination_recovered)
        await event_bus.subscribe(NetworkStatusChanged, self.handle_network_status_changed)
        await event_bus.subscribe(FileStatusChangedEvent, self.handle_file_status_changed)
        await event_bus.subscribe(StorageStatusChangedEvent, self.handle_storage_status_changed)
        await event_bus.subscribe(MountStatusChangedEvent, self.handle_mount_status_changed)
        await event_bus.subscribe(ScannerStatusChangedEvent, self.handle_scanner_status_changed)
        
        logging.info("GlobalEventLogger: Alle event handlers registreret med event bus")

    async def _add_log(
        self, 
        event: DomainEvent, 
        message: str, 
        level: str, 
        context: Optional[dict] = None
    ):
        """Tilføjer en ny, formateret logbesked til listen."""
        log_entry = LoggedEvent(
            timestamp=event.timestamp,
            event_type=type(event).__name__,
            message=message,
            level=level,
            context=context
        )
        async with self._lock:
            self._events.appendleft(log_entry)  # Tilføj i starten (nyeste først)

    async def get_all_logs(self, limit: Optional[int] = None) -> List[dict]:
        """Henter alle gemte logs (thread-safe) med optional limit."""
        async with self._lock:
            events_to_return = list(self._events)
            if limit:
                events_to_return = events_to_return[:limit]
            return [entry.to_dict() for entry in events_to_return]

    async def get_logs_by_level(self, level: str, limit: Optional[int] = None) -> List[dict]:
        """Henter logs filtreret efter level (ERROR, WARNING, INFO)."""
        async with self._lock:
            filtered_events = [entry for entry in self._events if entry.level == level]
            if limit:
                filtered_events = filtered_events[:limit]
            return [entry.to_dict() for entry in filtered_events]

    async def clear_logs(self):
        """Rydder alle logs (for maintenance)."""
        async with self._lock:
            self._events.clear()
        logging.info("GlobalEventLogger: Alle logs ryddet")

    def get_events(self, limit: Optional[int] = None, level: Optional[str] = None) -> List:
        """
        Sync metode for API adgang til events.
        Returnerer LoggedEvent objekter direkte (ikke dicts).
        """
        events_list = list(self._events)
        
        # Filter by level if specified
        if level:
            events_list = [event for event in events_list if event.level.lower() == level.lower()]
        
        # Apply limit if specified
        if limit:
            events_list = events_list[:limit]
            
        return events_list

    # --- Event Handlers (Disse kaldes af EventBus) ---

    async def handle_destination_unavailable(self, event):
        """Handler for DestinationUnavailableEvent"""
        from app.core.events.storage_events import DestinationUnavailableEvent
        if isinstance(event, DestinationUnavailableEvent):
            await self._add_log(
                event, 
                f"🔴 Destination utilgængelig: {event.reason}", 
                "ERROR",
                {"reason": event.reason}
            )

    async def handle_destination_recovered(self, event):
        """Handler for DestinationRecoveredEvent"""
        from app.core.events.storage_events import DestinationRecoveredEvent
        if isinstance(event, DestinationRecoveredEvent):
            await self._add_log(
                event, 
                f"✅ Destination recovered: {event.reason}", 
                "INFO",
                {"reason": event.reason}
            )

    async def handle_network_status_changed(self, event):
        """Handler for NetworkStatusChanged"""
        # Import here to avoid circular imports
        try:
            # Try both possible locations for this event
            from app.core.events.storage_events import NetworkStatusChanged
            if isinstance(event, NetworkStatusChanged):
                if not event.available:
                    await self._add_log(
                        event, 
                        f"🔴 Netværk nede: {event.reason} (kilde: {event.source})", 
                        "ERROR",
                        {"source": event.source, "reason": event.reason}
                    )
                else:
                    await self._add_log(
                        event, 
                        f"🌐 Netværk recovered: {event.reason} (kilde: {event.source})", 
                        "INFO",
                        {"source": event.source, "reason": event.reason}
                    )
        except ImportError:
            # Fallback for different event structure
            if hasattr(event, 'available'):
                status = "nede" if not event.available else "recovered"
                level = "ERROR" if not event.available else "INFO"
                await self._add_log(
                    event, 
                    f"🌐 Netværk {status}", 
                    level
                )

    async def handle_network_failure_detected(self, event):
        """Handler for NetworkFailureDetectedEvent"""
        from app.core.events.storage_events import NetworkFailureDetectedEvent
        if isinstance(event, NetworkFailureDetectedEvent):
            await self._add_log(
                event, 
                f"🔥 Netværksfejl under kopiering: {event.error_message}", 
                "ERROR",
                {
                    "file_id": event.file_id,
                    "operation": event.operation,
                    "error": event.error_message
                }
            )

    async def handle_file_copy_failed(self, event):
        """Handler for FileCopyFailedEvent"""
        # Check multiple possible locations for this event
        try:
            from app.core.events.file_events import FileCopyFailedEvent
            if isinstance(event, FileCopyFailedEvent):
                await self._add_log(
                    event, 
                    f"⚠️ Filkopiering fejlede: {event.error_message}", 
                    "WARNING",
                    {"file_path": getattr(event, 'file_path', 'unknown')}
                )
        except (ImportError, AttributeError):
            # Fallback for different event structure
            if hasattr(event, 'error_message'):
                await self._add_log(
                    event, 
                    f"⚠️ Filkopiering fejlede: {event.error_message}", 
                    "WARNING"
                )

    async def handle_file_status_changed(self, event):
        """Handler for FileStatusChangedEvent - log status transitions to failed/error states"""
        try:
            from app.core.events.file_events import FileStatusChangedEvent
            from app.models import FileStatus
            
            if isinstance(event, FileStatusChangedEvent):
                # Only log transitions to error states for UI visibility
                if hasattr(event, 'new_status'):
                    if event.new_status in [FileStatus.FAILED, FileStatus.SPACE_ERROR]:
                        status_emoji = "❌" if event.new_status == FileStatus.FAILED else "💾"
                        await self._add_log(
                            event, 
                            f"{status_emoji} Fil status: {event.file_path} → {event.new_status.value}", 
                            "WARNING",
                            {
                                "file_path": event.file_path,
                                "old_status": getattr(event, 'old_status', 'unknown'),
                                "new_status": event.new_status.value
                            }
                        )
        except (ImportError, AttributeError):
            pass  # Skip if event structure doesn't match

    async def handle_storage_status_changed(self, event):
        """Handler for StorageStatusChangedEvent"""
        try:
            from app.core.events.storage_events import StorageStatusChangedEvent
            from app.models import StorageStatus
            
            if isinstance(event, StorageStatusChangedEvent):
                # Log storage status changes for UI visibility
                update = event.update
                status_emoji = "✅" if update.new_status == StorageStatus.OK else "⚠️"
                level = "INFO" if update.new_status == StorageStatus.OK else "WARNING"
                
                await self._add_log(
                    event, 
                    f"{status_emoji} Storage status: {update.storage_info.location} → {update.new_status.value}", 
                    level,
                    {
                        "storage_type": update.storage_type,
                        "old_status": update.old_status.value if update.old_status else None,
                        "new_status": update.new_status.value,
                        "location": update.storage_info.location,
                        "free_space": f"{update.storage_info.free_space_gb:.1f} GB" if update.storage_info.free_space_gb else "unknown",
                        "total_space": f"{update.storage_info.total_space_gb:.1f} GB" if update.storage_info.total_space_gb else "unknown"
                    }
                )
        except (ImportError, AttributeError):
            pass  # Skip if event structure doesn't match

    async def handle_mount_status_changed(self, event):
        """Handler for MountStatusChangedEvent"""
        try:
            from app.core.events.storage_events import MountStatusChangedEvent
            from app.models import MountStatus
            
            if isinstance(event, MountStatusChangedEvent):
                # Log mount status changes for UI visibility
                update = event.update
                status_emoji = "✅" if update.mount_status == MountStatus.SUCCESS else "❌"
                level = "INFO" if update.mount_status == MountStatus.SUCCESS else "ERROR"
                
                await self._add_log(
                    event, 
                    f"{status_emoji} Mount status: {update.storage_type} → {update.mount_status.value}", 
                    level,
                    {
                        "storage_type": update.storage_type,
                        "mount_status": update.mount_status.value,
                        "share_url": update.share_url,
                        "mount_path": update.mount_path
                    }
                )
        except (ImportError, AttributeError):
            pass  # Skip if event structure doesn't match

    async def handle_scanner_status_changed(self, event):
        """Handler for ScannerStatusChangedEvent"""
        try:
            from app.core.events.scanner_events import ScannerStatusChangedEvent
            
            if isinstance(event, ScannerStatusChangedEvent):
                # Log scanner status changes for UI visibility  
                status_emoji = "🔍" if event.is_active else "⏹️"
                level = "INFO"
                
                status_text = "started" if event.is_active else "stopped"
                await self._add_log(
                    event, 
                    f"{status_emoji} File scanner {status_text}", 
                    level,
                    {
                        "is_active": event.is_active,
                        "service_name": getattr(event, 'service_name', 'unknown')
                    }
                )
        except (ImportError, AttributeError):
            pass  # Skip if event structure doesn't match

    # Generic handler for any unhandled events we might want to log
    async def handle_generic_event(self, event: DomainEvent):
        """Generic handler for events not specifically handled above"""
        await self._add_log(
            event,
            f"📋 System event: {type(event).__name__}",
            "INFO"
        )