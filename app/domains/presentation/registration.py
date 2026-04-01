# app/domains/presentation/registration.py

import logging
from app.core.cqrs.query_bus import QueryBus
from app.core.events.event_bus import DomainEventBus # <-- 1. Importer EventBus
from app.dependencies import (
    get_file_repository, 
    get_storage_monitor,
    get_presentation_event_handlers # <-- 2. Importer din handler-getter
)

# Importer de queries, den håndterer (som før)
from app.domains.presentation.queries import GetStatisticsQuery, GetAllFilesQuery, GetRecentFilesQuery, GetStorageStatusQuery
from app.domains.presentation.query_handlers import GetStatisticsQueryHandler, GetAllFilesQueryHandler, GetRecentFilesQueryHandler, GetStorageStatusQueryHandler

# Importer de events, den skal lytte til (NYT)
from app.core.events.file_events import FileStatusChangedEvent, FileCopyProgressEvent, FileDiscoveredEvent, FileCopyCompletedEvent
from app.core.events.scanner_events import ScannerStatusChangedEvent
from app.core.events.storage_events import MountStatusChangedEvent, StorageStatusChangedEvent
from app.domains.ingest_monitor.events import (
    IngestStatusUpdatedEvent, 
    ChannelErrorDetectedEvent,
    IngestOnlineEvent,
    IngestOfflineEvent,
    RecordingPathsDiscoveredEvent,
    AutoStopWarningEvent,
    AutoStopTriggeredEvent,
)
from app.domains.tally_light.monitor_service import (
    TallySwitchStatusUpdatedEvent,
    TallySwitchOnlineEvent,
    TallySwitchOfflineEvent,
)

# 3. Gør funktionen async og tilføj event_bus
async def register_presentation_domain(query_bus: QueryBus, event_bus: DomainEventBus):
    """Register all Presentation Layer CQRS handlers AND Event subscribers."""
    
    # --- Del 1: Registrer CQRS Handlers (som før) ---
    logging.info("Registrerer 'Presentation Layer' CQRS handlers...")
    if not query_bus.is_registered(GetStatisticsQuery):
        file_repository = get_file_repository()
        storage_monitor = get_storage_monitor()

        query_bus.register(GetStatisticsQuery, GetStatisticsQueryHandler(file_repository).handle)
        query_bus.register(GetAllFilesQuery, GetAllFilesQueryHandler(file_repository).handle)
        query_bus.register(GetRecentFilesQuery, GetRecentFilesQueryHandler(file_repository).handle)
        query_bus.register(GetStorageStatusQuery, GetStorageStatusQueryHandler(storage_monitor).handle)

    # --- Del 2: Registrer Event Subscribers (NYT) ---
    logging.info("Abonnerer på 'Presentation Layer' event handlers...")
    
    # 4. Hent den singleton-instans af dine handlers
    handlers = get_presentation_event_handlers()
    
    # 5. Flyt al abonnementslogik hertil
    await event_bus.subscribe(FileDiscoveredEvent, handlers.handle_file_discovered_event)
    await event_bus.subscribe(FileStatusChangedEvent, handlers.handle_file_status_changed_event)
    await event_bus.subscribe(FileCopyProgressEvent, handlers.handle_file_copy_progress)
    await event_bus.subscribe(FileCopyCompletedEvent, handlers.handle_file_copy_completed)
    await event_bus.subscribe(ScannerStatusChangedEvent, handlers.handle_scanner_status_event)
    await event_bus.subscribe(StorageStatusChangedEvent, handlers.handle_storage_status_event)
    await event_bus.subscribe(MountStatusChangedEvent, handlers.handle_mount_status_event)
    
    # Subscribe to ingest monitor events for real-time UI updates
    await event_bus.subscribe(IngestStatusUpdatedEvent, handlers.handle_ingest_status_updated_event)
    await event_bus.subscribe(ChannelErrorDetectedEvent, handlers.handle_channel_error_detected_event)
    await event_bus.subscribe(IngestOnlineEvent, handlers.handle_ingest_online_event)
    await event_bus.subscribe(IngestOfflineEvent, handlers.handle_ingest_offline_event)
    await event_bus.subscribe(RecordingPathsDiscoveredEvent, handlers.handle_recording_paths_discovered_event)
    
    # Subscribe to auto-stop events for real-time UI notifications
    await event_bus.subscribe(AutoStopWarningEvent, handlers.handle_auto_stop_warning_event)
    await event_bus.subscribe(AutoStopTriggeredEvent, handlers.handle_auto_stop_triggered_event)
    
    # Subscribe to tally switch events for real-time UI updates
    await event_bus.subscribe(TallySwitchStatusUpdatedEvent, handlers.handle_tally_switch_status_updated_event)
    await event_bus.subscribe(TallySwitchOnlineEvent, handlers.handle_tally_switch_online_event)
    await event_bus.subscribe(TallySwitchOfflineEvent, handlers.handle_tally_switch_offline_event)
    
    logging.info("Presentation domain-registrering (CQRS & Events) fuldført.")