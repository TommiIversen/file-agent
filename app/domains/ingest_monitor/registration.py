"""
Ingest Monitor Domain Registration

This module handles the registration of ingest monitor domain components
into the CQRS infrastructure.
"""

import logging
from app.core.cqrs.command_bus import CommandBus
from app.core.cqrs.query_bus import QueryBus
from app.core.events.event_bus import DomainEventBus
from .queries import GetIngestStatusQuery
from .commands import ClearAllChannelErrorsCommand, StartAllChannelsCommand, StopAllChannelsCommand
from .handlers import GetIngestStatusQueryHandler, ClearAllChannelErrorsCommandHandler, StartAllChannelsCommandHandler, StopAllChannelsCommandHandler


def register_ingest_monitor_domain(
    command_bus: CommandBus, 
    query_bus: QueryBus, 
    event_bus: DomainEventBus,
    ingest_monitor_worker
) -> None:
    """
    Register all ingest monitor domain components.
    
    Args:
        command_bus: The command bus for command handlers
        query_bus: The query bus for query handlers  
        event_bus: The event bus for event handlers
        ingest_monitor_worker: The worker instance for dependency injection
    """
    logging.info("Registering 'IngestMonitor' domain handlers...")

    # Register query handlers
    query_handler = GetIngestStatusQueryHandler(ingest_monitor_worker)
    query_bus.register(GetIngestStatusQuery, query_handler.handle)
    
    # Register command handlers
    clear_command_handler = ClearAllChannelErrorsCommandHandler(ingest_monitor_worker)
    command_bus.register(ClearAllChannelErrorsCommand, clear_command_handler.handle)
    
    start_command_handler = StartAllChannelsCommandHandler(ingest_monitor_worker)
    command_bus.register(StartAllChannelsCommand, start_command_handler.handle)
    
    stop_command_handler = StopAllChannelsCommandHandler(ingest_monitor_worker)
    command_bus.register(StopAllChannelsCommand, stop_command_handler.handle)
    
    logging.info("IngestMonitor domain registration completed")