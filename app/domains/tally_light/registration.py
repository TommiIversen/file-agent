"""
Tally Light Domain Registration

Register all event handlers for the tally light domain.
"""
import logging

from app.core.events.event_bus import DomainEventBus
from app.core.cqrs.command_bus import CommandBus
from app.core.events.ingest_events import IngestStatusUpdatedEvent, AutoStopWarningEvent
from .event_handlers import TallyLightEventHandler


async def register_tally_light_domain(
    command_bus: CommandBus, 
    event_bus: DomainEventBus, 
    handler: TallyLightEventHandler
) -> None:
    """
    Register all event subscriptions for the TallyLight domain.
    
    This function is responsible solely for wiring up the tally light
    domain's event handlers to the event bus infrastructure.
    """
    logging.info("Registering 'TallyLight' domain handlers...")

    # Subscribe to the complete snapshot event from IngestMonitorService
    await event_bus.subscribe(
        IngestStatusUpdatedEvent, 
        handler.handle_ingest_status_update
    )

    # Subscribe to auto-stop warning — forces blink before time limit
    await event_bus.subscribe(
        AutoStopWarningEvent,
        handler.handle_auto_stop_warning
    )

    logging.info("TallyLight domain handlers registered successfully")