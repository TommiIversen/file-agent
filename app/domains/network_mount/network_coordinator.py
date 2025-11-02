"""
NetworkCoordinator - Central koordinator for netværksstatus! 🚀

Denne klasse er hjertet i vores nye event-baserede netværksarkitektur.
Den lytter efter events fra flere kilder og publicerer autoritativ NetworkStatusChanged.

Event Sources:
- NetworkFailureDetectedEvent (fra copy operations - øjeblikkelig fejl)
- DestinationUnavailableEvent (fra StorageMonitor - periodisk fejl)  
- DestinationRecoveredEvent (fra StorageMonitor - recovery)

Event Output:
- NetworkStatusChanged (autoritativ status til alle subscribers)
"""
import logging
from typing import Optional
from datetime import datetime

from app.core.events.event_bus import DomainEventBus
from app.core.events.storage_events import (
    NetworkFailureDetectedEvent,
    DestinationUnavailableEvent, 
    DestinationRecoveredEvent,
    NetworkStatusChanged
)

logger = logging.getLogger(__name__)


class NetworkCoordinator:
    """
    🎯 Central koordinator for alle netværksstatus-beslutninger.
    
    Implementerer Smart Network Status Logic:
    - Øjeblikkelig fejl fra copy operations trigger omgående status change
    - Periodisk fejl fra StorageMonitor bekræfter langvarig utilgængelighed
    - Recovery events genopretter status når netværk er stabilt igen
    
    Single Source of Truth for netværksstatus i hele applikationen! 
    """
    
    def __init__(self, event_bus: DomainEventBus):
        self._event_bus = event_bus
        self._network_available: bool = True
        self._last_status_change: Optional[datetime] = None
        self._last_failure_reason: Optional[str] = None
        logger.info("🚀 NetworkCoordinator initialized - network status: AVAILABLE")

    @property 
    def is_network_available(self) -> bool:
        """Nuværende netværksstatus (readonly)"""
        return self._network_available

    @property
    def last_status_change(self) -> Optional[datetime]:
        """Tidspunkt for sidste status ændring"""
        return self._last_status_change

    @property 
    def last_failure_reason(self) -> Optional[str]:
        """Årsag til sidste fejl (hvis network unavailable)"""
        return self._last_failure_reason

    async def handle_network_failure_detected(self, event: NetworkFailureDetectedEvent):
        """
        🔥 Håndter øjeblikkelig netværksfejl fra copy operationer.
        
        Dette er ØJEBLIKKELIG feedback - reagér hurtigt!
        """
        logger.warning(
            f"🔥 ØJEBLIKKELIG netværksfejl detekteret! "
            f"File: {event.file_id}, Operation: {event.operation}, "
            f"Error: {event.error_message}"
        )
        
        await self._update_network_status(
            available=False,
            reason=f"Copy failure: {event.error_message}",
            source="copy_failure"
        )

    async def handle_destination_unavailable(self, event: DestinationUnavailableEvent):
        """
        📡 Håndter periodisk fejl fra StorageMonitor.
        
        Dette bekræfter langvarig utilgængelighed.
        """
        logger.warning(
            f"📡 StorageMonitor bekræfter destination utilgængelig: {event.reason}"
        )
        
        await self._update_network_status(
            available=False, 
            reason=f"Storage monitor: {event.reason}",
            source="periodic_check"
        )

    async def handle_destination_recovered(self, event: DestinationRecoveredEvent):
        """
        ✅ Håndter recovery fra StorageMonitor.
        
        Netværk er igen tilgængeligt!
        """
        logger.info(
            f"✅ Netværk RECOVERED! StorageMonitor rapporterer: {event.reason}"
        )
        
        await self._update_network_status(
            available=True,
            reason=f"Recovery: {event.reason}", 
            source="recovery"
        )

    async def _update_network_status(self, available: bool, reason: str, source: str):
        """
        🎯 Opdater netværksstatus og publicer autoritativ NetworkStatusChanged.
        
        Args:
            available: Er netværk tilgængeligt? 
            reason: Årsag til status ændring
            source: Kilde til ændringen ("copy_failure", "periodic_check", "recovery")
        """
        print(f"DEBUG: _update_network_status called with available={available}")
        previous_status = self._network_available
        self._network_available = available
        self._last_status_change = datetime.now()
        
        print(f"DEBUG: Setting network available to {available}")
        
        if not available:
            self._last_failure_reason = reason
        else:
            self._last_failure_reason = None

        status_text = "AVAILABLE" if available else "UNAVAILABLE"
        
        print(f"DEBUG: Status change check - previous: {previous_status}, current: {available}")
        
        # Log kun hvis status faktisk ændrer sig
        if previous_status != available:
            print("DEBUG: Status changed! Publishing event...")
            logger.info(
                f"🎯 NETWORK STATUS CHANGED: {status_text} "
                f"(reason: {reason}, source: {source})"
            )
            
            # 🚀 PUBLICER AUTORITATIV EVENT!
            event = NetworkStatusChanged(
                available=available,
                reason=reason,
                source=source
            )
            
            print("DEBUG: About to publish event...")
            # Await event publishing for testing (normally fire-and-forget)
            await self._event_bus.publish(event)
            print("DEBUG: Event published successfully!")
        else:
            print("DEBUG: Status unchanged, skipping event publishing")
            logger.debug(
                f"Network status uændret ({status_text}), "
                f"men opdateret reason: {reason} (source: {source})"
            )
        
        print("DEBUG: _update_network_status complete")

    async def get_status_summary(self) -> dict:
        """
        📊 Få komplet status sammenfatning for debugging/monitoring.
        """
        return {
            "network_available": self._network_available,
            "last_status_change": self._last_status_change.isoformat() if self._last_status_change else None,
            "last_failure_reason": self._last_failure_reason,
            "coordinator_active": True
        }