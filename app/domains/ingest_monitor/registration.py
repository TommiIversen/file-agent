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
from .handlers import GetIngestStatusQueryHandler
from .service import IngestMonitorService


def register_ingest_monitor_domain(
    command_bus: CommandBus, 
    query_bus: QueryBus, 
    event_bus: DomainEventBus,
    ingest_monitor_service: IngestMonitorService
) -> None:
    """
    Register all ingest monitor domain components.
    
    Args:
        command_bus: The command bus for command handlers
        query_bus: The query bus for query handlers  
        event_bus: The event bus for event handlers
        ingest_monitor_service: The service instance for dependency injection
    """
    logging.info("Registering 'IngestMonitor' domain handlers...")

    # Register query handlers
    query_handler = GetIngestStatusQueryHandler(ingest_monitor_service)
    query_bus.register(GetIngestStatusQuery, query_handler.handle)
    
    logging.info("IngestMonitor domain registration completed")