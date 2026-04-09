"""
Ingest monitor factories.

IngestApiClient, IngestStateService, IngestMonitorWorker.
"""
from app.dependencies.core import (
    _singletons,
    get_settings,
    get_event_bus,
)
from app.domains.ingest_monitor.api_client import IngestApiClient
from app.domains.ingest_monitor.state_service import IngestStateService
from app.domains.ingest_monitor.worker import IngestMonitorWorker


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
