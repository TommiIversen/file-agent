"""
Service Registry for Global Service Access

Provides a centralized way to access singleton services across the application.
Used for services that need to be accessed from various parts of the codebase
without tight coupling.
"""
from typing import Optional
from app.domains.tally_light.monitor_service import TallySwitchMonitorService

# Global service registry
_tally_monitor_service: Optional[TallySwitchMonitorService] = None


def register_tally_monitor_service(service: TallySwitchMonitorService) -> None:
    """Register the tally switch monitor service globally."""
    global _tally_monitor_service
    _tally_monitor_service = service


def get_tally_monitor_service() -> Optional[TallySwitchMonitorService]:
    """Get the registered tally switch monitor service."""
    global _tally_monitor_service
    return _tally_monitor_service


def unregister_tally_monitor_service() -> None:
    """Unregister the tally switch monitor service."""
    global _tally_monitor_service
    _tally_monitor_service = None