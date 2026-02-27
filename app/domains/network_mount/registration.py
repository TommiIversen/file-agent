"""
Network Mount Domain Registration 

Registrerer NetworkCoordinator og alle network mount relaterede services.
Dette er hjertestykket i vores nye event-baserede netværksarkitektur!
"""
import logging
from app.core.events.event_bus import DomainEventBus
from app.core.events.storage_events import (
    NetworkFailureDetectedEvent,
    DestinationUnavailableEvent,
    DestinationRecoveredEvent
)
from app.domains.network_mount.network_coordinator import NetworkCoordinator

logger = logging.getLogger(__name__)


async def register_network_mount_domain(event_bus: DomainEventBus) -> dict:
    """
     Registrer Network Mount domænet med event subscriptions.
    
    Returns:
        dict: Domæne services for dependency injection
    """
    logger.info(" Registering Network Mount Domain...")
    
    # Opret NetworkCoordinator
    network_coordinator = NetworkCoordinator(event_bus)
    
    # Subscribe til alle relevante events
    await event_bus.subscribe(
        NetworkFailureDetectedEvent,
        network_coordinator.handle_network_failure_detected
    )
    logger.info(" Subscribed to NetworkFailureDetectedEvent")
    
    await event_bus.subscribe(
        DestinationUnavailableEvent, 
        network_coordinator.handle_destination_unavailable
    )
    logger.info(" Subscribed to DestinationUnavailableEvent")
    
    await event_bus.subscribe(
        DestinationRecoveredEvent,
        network_coordinator.handle_destination_recovered
    )
    logger.info(" Subscribed to DestinationRecoveredEvent")
    
    logger.info(" NetworkCoordinator is now the SINGLE SOURCE OF TRUTH for network status!")
    
    # Return services for DI container
    return {
        "network_coordinator": network_coordinator
    }