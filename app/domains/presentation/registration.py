# app/domains/presentation/registration.py

import logging
from app.core.cqrs.query_bus import QueryBus
from app.core.events.event_bus import DomainEventBus  # <-- 1. Importer EventBus
from app.dependencies import (
    get_file_repository, 
    get_storage_monitor,
    get_presentation_event_handlers  # <-- 2. Importer din handler-getter
)

# Importer de queries, den håndterer (som før)
from app.domains.presentation.queries import GetStatisticsQuery, GetAllFilesQuery, GetStorageStatusQuery
from app.domains.presentation.query_handlers import GetStatisticsQueryHandler, GetAllFilesQueryHandler, GetStorageStatusQueryHandler

# Importer de events, den skal lytte til (NYT)
from app.core.events.file_events import FileStatusChangedEvent, FileCopyProgressEvent
from app.core.events.scanner_events import ScannerStatusChangedEvent
from app.core.events.storage_events import MountStatusChangedEvent, StorageStatusChangedEvent

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
        query_bus.register(GetStorageStatusQuery, GetStorageStatusQueryHandler(storage_monitor).handle)

    # --- Del 2: Registrer Event Subscribers (NYT) ---
    logging.info("Abonnerer på 'Presentation Layer' event handlers...")
    
    # 4. Hent den singleton-instans af dine handlers
    handlers = get_presentation_event_handlers()
    
    # 5. Flyt al abonnementslogik hertil
    await event_bus.subscribe(FileStatusChangedEvent, handlers.handle_file_status_changed_event)
    await event_bus.subscribe(FileCopyProgressEvent, handlers.handle_file_copy_progress)
    await event_bus.subscribe(ScannerStatusChangedEvent, handlers.handle_scanner_status_event)
    await event_bus.subscribe(StorageStatusChangedEvent, handlers.handle_storage_status_event)
    await event_bus.subscribe(MountStatusChangedEvent, handlers.handle_mount_status_event)
    
    logging.info("Presentation domain-registrering (CQRS & Events) fuldført.")