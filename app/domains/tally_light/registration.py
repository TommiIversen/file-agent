"""
Tally Light Domain Registration

Register all event handlers for the tally light domain.
"""
import logging

from app.core.events.event_bus import DomainEventBus
from app.core.cqrs.command_bus import CommandBus
from app.core.cqrs.query_bus import QueryBus
from app.core.cqrs.shared_queries import GetTallySwitchStatusQuery
from app.core.events.ingest_events import IngestStatusUpdatedEvent, AutoStopWarningEvent
from .event_handlers import TallyLightEventHandler
from .monitor_service import TallySwitchMonitorService
from .query_handlers import GetTallySwitchStatusQueryHandler


async def register_tally_light_domain(
    command_bus: CommandBus,
    query_bus: QueryBus,
    event_bus: DomainEventBus,
    handler: TallyLightEventHandler,
    switch_monitor: TallySwitchMonitorService,
) -> None:
    """
    Register all event subscriptions and query handlers for the TallyLight domain.
    """
    logging.info("Registering 'TallyLight' domain handlers...")

    # Register query handlers
    query_bus.register(
        GetTallySwitchStatusQuery,
        GetTallySwitchStatusQueryHandler(switch_monitor).handle,
    )

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