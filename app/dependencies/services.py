"""
Domain service factories.

Presentation, directory browsing, lifecycle, tally light, ingest monitor.
"""
from app.dependencies.core import (
    _singletons,
    get_settings,
    get_command_bus,
    get_event_bus,
    get_file_repository,
)

from app.domains.presentation.websocket_manager import WebSocketManager
from app.domains.directory_browsing.service import DirectoryScannerService
from app.domains.presentation.event_handlers import PresentationEventHandlers
from app.domains.lifecycle.service import LifecycleService
from app.domains.tally_light.event_handlers import TallyLightEventHandler
from app.domains.tally_light.monitor_service import TallySwitchMonitorService
from app.domains.ingest_monitor.api_client import IngestApiClient
from app.domains.ingest_monitor.state_service import IngestStateService
from app.domains.ingest_monitor.worker import IngestMonitorWorker
from app.domains.tally_light.switch_clients import IPPower9255Client


def get_websocket_manager() -> WebSocketManager:
    """Gets the singleton instance of the pure WebSocketManager."""
    if "websocket_manager" not in _singletons:
        _singletons["websocket_manager"] = WebSocketManager()
    return _singletons["websocket_manager"]


def get_directory_scanner() -> DirectoryScannerService:
    if "directory_scanner" not in _singletons:
        _singletons["directory_scanner"] = DirectoryScannerService(get_settings())
    return _singletons["directory_scanner"]


def get_presentation_event_handlers() -> PresentationEventHandlers:
    if "presentation_event_handlers" not in _singletons:
        _singletons["presentation_event_handlers"] = PresentationEventHandlers(
            websocket_manager=get_websocket_manager(),
            file_repository=get_file_repository(),
        )
    return _singletons["presentation_event_handlers"]


def get_lifecycle_service() -> LifecycleService:
    """Get the LifecycleService singleton for background file cleanup."""
    if "lifecycle_service" not in _singletons:
        _singletons["lifecycle_service"] = LifecycleService(
            command_bus=get_command_bus(),
            settings=get_settings(),
        )
    return _singletons["lifecycle_service"]


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


def get_ingest_state_service() -> IngestStateService:
    """Get the IngestStateService singleton for channel state management."""
    if "ingest_state_service" not in _singletons:
        settings = get_settings()
        _singletons["ingest_state_service"] = IngestStateService(
            event_bus=get_event_bus(),
            auto_stop_minutes=settings.justin_auto_stop_minutes,
            auto_stop_warning_minutes=settings.justin_auto_stop_warning_minutes,
        )
    return _singletons["ingest_state_service"]


def get_ingest_api_client() -> IngestApiClient:
    """Get the IngestApiClient singleton for Just In Engine API communication."""
    if "ingest_api_client" not in _singletons:
        _singletons["ingest_api_client"] = IngestApiClient(
            settings=get_settings(),
        )
    return _singletons["ingest_api_client"]


def get_ingest_monitor_worker() -> IngestMonitorWorker:
    """Get the IngestMonitorWorker singleton - the refactored orchestration worker."""
    if "ingest_monitor_worker" not in _singletons:
        _singletons["ingest_monitor_worker"] = IngestMonitorWorker(
            settings=get_settings(),
            api_client=get_ingest_api_client(),
            state_service=get_ingest_state_service(),
        )
    return _singletons["ingest_monitor_worker"]
