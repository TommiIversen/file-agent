"""
Tally light factories.

TallyLightEventHandler, TallySwitchMonitorService.
"""
from app.dependencies.core import (
    _singletons,
    get_settings,
    get_event_bus,
)
from app.domains.tally_light.event_handlers import TallyLightEventHandler
from app.domains.tally_light.monitor_service import TallySwitchMonitorService
from app.domains.tally_light.switch_clients import IPPower9255Client


def get_tally_light_event_handler() -> TallyLightEventHandler:
    """Get the TallyLightEventHandler singleton for IP Power Switch control."""
    if "tally_light_event_handler" not in _singletons:
        _singletons["tally_light_event_handler"] = TallyLightEventHandler(
            settings=get_settings(),
        )
    return _singletons["tally_light_event_handler"]


def get_tally_switch_monitor() -> TallySwitchMonitorService:
    """Get the TallySwitchMonitorService singleton for IP Power Switch monitoring."""
    if "tally_switch_monitor" not in _singletons:
        settings = get_settings()
        ip_address = settings.tally_light_switch_ip

        switch_client = IPPower9255Client(
            ip_address=ip_address,
            username=settings.tally_light_switch_username,
            password=settings.tally_light_switch_password,
        )

        _singletons["tally_switch_monitor"] = TallySwitchMonitorService(
            switch_client=switch_client,
            ip_address=ip_address,
            event_bus=get_event_bus(),
        )
    return _singletons["tally_switch_monitor"]
