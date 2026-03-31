import asyncio
from functools import lru_cache
from typing import Dict, Any, Optional

from app.core.events.event_bus import DomainEventBus
from app.core.file_repository import FileRepository
from app.core.sqlite_file_repository import SqliteFileRepository
from app.core.sqlite_event_store import SqliteEventStore
from app.core.file_state_machine import FileStateMachine
from app.domains.file_processing.copy.file_copier_service import FileCopierService

from .config import Settings
from .domains.file_processing.consumer.job_error_classifier import JobErrorClassifier
from .domains.file_processing.consumer.job_copy_executor import JobCopyExecutor
from .domains.file_processing.consumer.job_space_manager import JobSpaceManager
from .domains.file_processing.consumer.job_finalization_service import JobFinalizationService
from .domains.file_processing.copy.growing_copy import GrowingFileCopyStrategy
from .domains.file_processing.copy.file_verification import FileVerificationService
from .domains.file_processing.copy.copy_io_loop import CopyIoLoop
from .domains.file_processing.job_queue import JobQueueService
from .domains.network_mount.mount_service import NetworkMountService
from .domains.file_discovery.file_scanner_service import FileScannerService
from .domains.file_processing.space_checker import SpaceChecker
from .domains.file_processing.space_retry_manager import SpaceRetryManager
from .domains.storage.storage_checker import StorageChecker
from .domains.storage.storage_monitor import StorageMonitorService
from .domains.presentation.websocket_manager import WebSocketManager
from app.domains.file_discovery.file_discovery_slice import FileDiscoverySlice

from app.core.cqrs.command_bus import CommandBus
from app.core.cqrs.query_bus import QueryBus

from app.domains.directory_browsing.service import DirectoryScannerService
from app.domains.presentation.event_handlers import PresentationEventHandlers
from app.domains.lifecycle.service import LifecycleService
from app.domains.tally_light.event_handlers import TallyLightEventHandler
from app.domains.tally_light.monitor_service import TallySwitchMonitorService
from app.domains.ingest_monitor.api_client import IngestApiClient
from app.domains.ingest_monitor.state_service import IngestStateService
from app.domains.ingest_monitor.worker import IngestMonitorWorker
from app.core.global_event_logger import GlobalEventLogger
from app.domains.tally_light.switch_clients import IPPower9255Client

# Global singleton instances
_singletons: Dict[str, Any] = {}

@lru_cache
def get_settings() -> Settings:
    """Hent Settings singleton instance."""
    return Settings()

def get_command_bus() -> CommandBus:
    if "command_bus" not in _singletons:
        _singletons["command_bus"] = CommandBus()
    return _singletons["command_bus"]

def get_query_bus() -> QueryBus:
    if "query_bus" not in _singletons:
        _singletons["query_bus"] = QueryBus()
    return _singletons["query_bus"]


def get_event_bus() -> "DomainEventBus":
    if "event_bus" not in _singletons:
        _singletons["event_bus"] = DomainEventBus()
    return _singletons["event_bus"]


def get_file_repository() -> SqliteFileRepository:
    if "file_repository" not in _singletons:
        settings = get_settings()
        _singletons["file_repository"] = SqliteFileRepository(settings.database_path)
    return _singletons["file_repository"]

def get_file_state_machine() -> FileStateMachine:
    if "file_state_machine" not in _singletons:
        _singletons["file_state_machine"] = FileStateMachine(
            file_repository=get_file_repository(),
            event_bus=get_event_bus()
        )
    return _singletons["file_state_machine"]

def get_file_discovery_slice() -> FileDiscoverySlice:
    """Get the File Discovery vertical slice."""
    if "file_discovery_slice" not in _singletons:
        file_repository = get_file_repository()
        event_bus = get_event_bus()
        state_machine = get_file_state_machine()
        settings = get_settings()
        _singletons["file_discovery_slice"] = FileDiscoverySlice(
            file_repository=file_repository,
            event_bus=event_bus,
            state_machine=state_machine,
            cooldown_minutes=settings.space_error_cooldown_minutes
        )
    return _singletons["file_discovery_slice"]


def get_file_scanner() -> FileScannerService:
    if "file_scanner" not in _singletons:        
        _singletons["file_scanner"] = FileScannerService(
            settings=get_settings(),
            command_bus=get_command_bus(),
            query_bus=get_query_bus(),
            storage_monitor=get_storage_monitor(),
            event_bus=get_event_bus()
        )
    return _singletons["file_scanner"]


def get_job_queue_service() -> JobQueueService:
    if "job_queue_service" not in _singletons:
        _singletons["job_queue_service"] = JobQueueService(
            settings=get_settings(), 
            file_repository=get_file_repository(), 
            event_bus=get_event_bus(),
            state_machine=get_file_state_machine(),
        )
            
    return _singletons["job_queue_service"]


def get_file_copier() -> FileCopierService:
    if "file_copier" not in _singletons:
        _singletons["file_copier"] = FileCopierService(
            settings=get_settings(),
            job_queue=get_job_queue_service(),
            command_bus=get_command_bus(),
        )
    return _singletons["file_copier"]


def get_space_checker() -> SpaceChecker:
    if "space_checker" not in _singletons:
        settings = get_settings()
        storage_monitor = get_storage_monitor()

        _singletons["space_checker"] = SpaceChecker(
            settings=settings, storage_monitor=storage_monitor
        )

    return _singletons["space_checker"]


def get_space_retry_manager() -> SpaceRetryManager:
    if "space_retry_manager" not in _singletons:
        _singletons["space_retry_manager"] = SpaceRetryManager(
            settings=get_settings(),
            file_repository=get_file_repository(),
            event_bus=get_event_bus(),
            state_machine=get_file_state_machine()
        )
    return _singletons["space_retry_manager"]


def get_job_finalization_service() -> JobFinalizationService:
    if "job_finalization_service" not in _singletons:
        _singletons["job_finalization_service"] = JobFinalizationService(
            settings=get_settings(),
            file_repository=get_file_repository(),
            event_bus=get_event_bus(),
            state_machine=get_file_state_machine()
        )
    return _singletons["job_finalization_service"]


def get_job_copy_executor() -> JobCopyExecutor:
    if "job_copy_executor" not in _singletons:
        _singletons["job_copy_executor"] = JobCopyExecutor(
            settings=get_settings(),
            file_repository=get_file_repository(),
            copy_strategy=get_copy_strategy(),
            state_machine=get_file_state_machine(), # <-- TILFØJ DENNE
            error_classifier=get_job_error_classifier(),
            event_bus=get_event_bus()
        )
    return _singletons["job_copy_executor"]


def get_job_space_manager() -> JobSpaceManager:
    if "job_space_manager" not in _singletons:
        _singletons["job_space_manager"] = JobSpaceManager(
            settings=get_settings(),
            file_repository=get_file_repository(),
            space_checker=get_space_checker(),
            state_machine=get_file_state_machine(),
            retry_manager=get_space_retry_manager(),
            event_bus=get_event_bus()
        )
    return _singletons["job_space_manager"]


def get_websocket_manager() -> WebSocketManager:
    """Gets the singleton instance of the pure WebSocketManager."""
    if "websocket_manager" not in _singletons:
        _singletons["websocket_manager"] = WebSocketManager()
    return _singletons["websocket_manager"]


def get_storage_checker() -> StorageChecker:
    if "storage_checker" not in _singletons:
        settings = get_settings()
        _singletons["storage_checker"] = StorageChecker(
            test_file_prefix=settings.storage_test_file_prefix
        )

    return _singletons["storage_checker"]


def get_network_mount_service() -> NetworkMountService:
    if "network_mount_service" not in _singletons:
        settings = get_settings()
        _singletons["network_mount_service"] = NetworkMountService(settings)

    return _singletons["network_mount_service"]


def get_network_coordinator():
    """
     Get NetworkCoordinator - Single Source of Truth for network status!
    
    Returns the NetworkCoordinator instance that was created during
    network_mount domain registration.
    """
    if "network_coordinator" not in _singletons:
        raise RuntimeError("NetworkCoordinator not initialized! Ensure register_network_mount_domain() was called.")
    
    return _singletons["network_coordinator"]


def register_network_coordinator(coordinator) -> None:
    """Register the NetworkCoordinator singleton after domain registration."""
    _singletons["network_coordinator"] = coordinator


def get_storage_monitor() -> StorageMonitorService:
    if "storage_monitor" not in _singletons:
        _singletons["storage_monitor"] = StorageMonitorService(
            settings=get_settings(),
            storage_checker=get_storage_checker(),
            event_bus=get_event_bus(),
            network_mount_service=get_network_mount_service()
        )
        
    return _singletons["storage_monitor"]


def get_job_error_classifier() -> JobErrorClassifier:
    if "job_error_classifier" not in _singletons:
        _singletons["job_error_classifier"] = JobErrorClassifier(storage_monitor=get_storage_monitor())
    return _singletons["job_error_classifier"]


def get_copy_strategy() -> GrowingFileCopyStrategy:
    if "copy_strategy" not in _singletons:
        _singletons["copy_strategy"] = GrowingFileCopyStrategy(
            settings=get_settings(),
            file_repository=get_file_repository(),
            event_bus=get_event_bus(),
            state_machine=get_file_state_machine(),
            verification_service=get_file_verification_service(), # <-- NY
            io_loop=get_copy_io_loop() # <-- NY
        )
    return _singletons["copy_strategy"]


def get_file_verification_service() -> FileVerificationService:
    if "file_verification_service" not in _singletons:
        _singletons["file_verification_service"] = FileVerificationService()
    return _singletons["file_verification_service"]


def get_copy_io_loop() -> CopyIoLoop:
    if "copy_io_loop" not in _singletons:
        _singletons["copy_io_loop"] = CopyIoLoop(
            settings=get_settings(),
            state_machine=get_file_state_machine(),
            event_bus=get_event_bus()
        )
    return _singletons["copy_io_loop"]


async def get_job_queue() -> Optional[asyncio.Queue]:
    job_queue_service = get_job_queue_service()
    return job_queue_service.job_queue


def get_directory_scanner() -> DirectoryScannerService:
    if "directory_scanner" not in _singletons:
        _singletons["directory_scanner"] = DirectoryScannerService(get_settings())
    return _singletons["directory_scanner"]

def get_presentation_event_handlers() -> PresentationEventHandlers:
    if "presentation_event_handlers" not in _singletons:
        websocket_manager = get_websocket_manager()
        file_repository = get_file_repository()
        _singletons["presentation_event_handlers"] = PresentationEventHandlers(
            websocket_manager=websocket_manager, file_repository=file_repository
        )
    return _singletons["presentation_event_handlers"]


def get_global_event_logger():
    """Get the GlobalEventLogger singleton for UI event visibility."""
    if "global_event_logger" not in _singletons:
        _singletons["global_event_logger"] = GlobalEventLogger()
    return _singletons["global_event_logger"]


def get_event_store() -> SqliteEventStore:
    """Get the SqliteEventStore singleton, sharing the DB connection from FileRepository."""
    if "event_store" not in _singletons:
        file_repo = get_file_repository()
        _singletons["event_store"] = SqliteEventStore(
            db=file_repo.connection,
            write_lock=file_repo.write_lock,
        )
    return _singletons["event_store"]


def get_lifecycle_service() -> LifecycleService:
    """
    Get the LifecycleService singleton for background file cleanup.
    
    This service is responsible for periodic cleanup of old,
    terminal files from the in-memory repository.
    """
    if "lifecycle_service" not in _singletons:
        _singletons["lifecycle_service"] = LifecycleService(
            command_bus=get_command_bus(),
            settings=get_settings()
        )
    return _singletons["lifecycle_service"]


def get_tally_light_event_handler() -> TallyLightEventHandler:
    """
    Get the TallyLightEventHandler singleton for IP Power Switch control.
    
    This handler is responsible for managing tally light states
    based on ingest recording status.
    """
    if "tally_light_event_handler" not in _singletons:
        _singletons["tally_light_event_handler"] = TallyLightEventHandler(
            settings=get_settings()
        )
    return _singletons["tally_light_event_handler"]


def get_tally_switch_monitor() -> TallySwitchMonitorService:
    """
    Get the TallySwitchMonitorService singleton for IP Power Switch monitoring.
    
    This service monitors the connectivity status of the tally switch hardware
    and publishes status updates via the event bus.
    """
    if "tally_switch_monitor" not in _singletons:
        settings = get_settings()
        # Get IP address from settings - use correct field name
        ip_address = settings.tally_light_switch_ip # From config.py
        
        # Create switch client with IP address
        switch_client = IPPower9255Client(
            ip_address=ip_address,
            username=settings.tally_light_switch_username,
            password=settings.tally_light_switch_password,
        )
        
        _singletons["tally_switch_monitor"] = TallySwitchMonitorService(
            switch_client=switch_client,
            ip_address=ip_address,
            event_bus=get_event_bus()
        )
    return _singletons["tally_switch_monitor"]


def get_ingest_state_service() -> IngestStateService:
    """
    Get the IngestStateService singleton for channel state management.
    
    This service is responsible for maintaining the channel status cache
    and detecting changes to publish appropriate events.
    """
    if "ingest_state_service" not in _singletons:
        settings = get_settings()
        _singletons["ingest_state_service"] = IngestStateService(
            event_bus=get_event_bus(),
            auto_stop_minutes=settings.justin_auto_stop_minutes,
            auto_stop_warning_minutes=settings.justin_auto_stop_warning_minutes,
        )
    return _singletons["ingest_state_service"]


def get_ingest_api_client() -> IngestApiClient:
    """
    Get the IngestApiClient singleton for Just In Engine API communication.
    
    This client is responsible for making HTTP requests to Just In Engine
    and validating API responses.
    """
    if "ingest_api_client" not in _singletons:
        _singletons["ingest_api_client"] = IngestApiClient(
            settings=get_settings()
        )
    return _singletons["ingest_api_client"]


def get_ingest_monitor_worker() -> IngestMonitorWorker:
    """
    Get the IngestMonitorWorker singleton - the refactored orchestration worker.
    
    This worker follows Single Responsibility Principle by only handling
    polling orchestration, delegating API calls to ApiClient and state
    management to StateService.
    """
    if "ingest_monitor_worker" not in _singletons:
        _singletons["ingest_monitor_worker"] = IngestMonitorWorker(
            settings=get_settings(),
            api_client=get_ingest_api_client(),
            state_service=get_ingest_state_service()
        )
    return _singletons["ingest_monitor_worker"]




def reset_singletons() -> None:
    global _singletons
    _singletons.clear()

