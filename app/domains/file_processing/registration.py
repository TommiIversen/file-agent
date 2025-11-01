"""
Registration and setup for File Processing Domain.

This module handles the registration of all CQRS handlers (event handlers,
command handlers) for the file processing domain with the command bus and event bus.
"""
from app.core.cqrs.command_bus import CommandBus
from app.core.events.event_bus import DomainEventBus
from app.dependencies import (
    get_job_queue_service, get_file_repository, get_file_state_machine, 
    get_storage_monitor, get_copy_strategy
)
from app.core.events.file_events import FileReadyEvent
from .event_handlers import FileProcessingEventHandler
from .command_handlers import QueueFileCommandHandler
from .commands import QueueFileCommand


async def register_file_processing_domain(
    command_bus: CommandBus, 
    event_bus: DomainEventBus
):
    """
    Registers all handlers for the File Processing domain.
    
    This function sets up the complete CQRS infrastructure for file processing:
    - Event handlers for domain events
    - Command handlers for business logic execution
    - Proper dependency injection for all handlers
    """

    # 1. Create Event Handler
    event_handler = FileProcessingEventHandler(
        command_bus=command_bus,
        file_repository=get_file_repository()
    )
    await event_bus.subscribe(FileReadyEvent, event_handler.handle_file_ready)

    # 2. Create Command Handlers
    job_queue_service = get_job_queue_service()
    queue_handler = QueueFileCommandHandler(
        job_queue_service=job_queue_service,  # Pass the service, not the queue
        file_repository=get_file_repository(),
        state_machine=get_file_state_machine(),
        storage_monitor=get_storage_monitor(),
        copy_strategy=get_copy_strategy()
    )
    command_bus.register(QueueFileCommand, queue_handler.handle)

    # Note: ProcessJobCommandHandler will be added in Phase 3
    # process_handler = ProcessJobCommandHandler(...)
    # command_bus.register(ProcessJobCommand, process_handler.handle)