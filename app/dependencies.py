import asyncio
from functools import lru_cache
from typing import Dict, Any, Optional

from app.core.events.event_bus import DomainEventBus
from app.core.file_repository import FileRepository
from app.core.file_state_machine import FileStateMachine
from app.services.copy.file_copier_service import FileCopierService

from .config import Settings
from .services.consumer.job_error_classifier import JobErrorClassifier
from .services.consumer.job_processor import JobProcessor
from .services.consumer.job_copy_executor import JobCopyExecutor
from .services.consumer.job_space_manager import JobSpaceManager
from .services.consumer.job_finalization_service import JobFinalizationService
from .services.copy.growing_copy import GrowingFileCopyStrategy
from .services.job_queue import JobQueueService
from .services.network_mount import NetworkMountService
from .domains.file_discovery.file_scanner_service import FileScannerService
from .services.space_checker import SpaceChecker
from .services.space_retry_manager import SpaceRetryManager
from .services.storage_checker import StorageChecker
from .services.storage_monitor import StorageMonitorService
from .domains.presentation.websocket_manager import WebSocketManager
from app.domains.file_discovery.file_discovery_slice import FileDiscoverySlice

from app.core.cqrs.command_bus import CommandBus
from app.core.cqrs.query_bus import QueryBus

from app.domains.directory_browsing.service import DirectoryScannerService
from app.domains.presentation.event_handlers import PresentationEventHandlers

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


def get_file_repository() -> FileRepository:
    if "file_repository" not in _singletons:
        _singletons["file_repository"] = FileRepository()
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
            storage_monitor=get_storage_monitor(),
            copy_strategy=get_copy_strategy()
        )
        
        # Set up the circular reference after both objects are created
        storage_monitor = get_storage_monitor()
        if storage_monitor._job_queue is None:
            storage_monitor._job_queue = _singletons["job_queue_service"]
            
    return _singletons["job_queue_service"]


def get_file_copier() -> FileCopierService:
    if "file_copier" not in _singletons:
        _singletons["file_copier"] = FileCopierService(
            settings=get_settings(),
            job_queue=get_job_queue_service(),
            job_processor=get_job_processor(),
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
            state_machine=get_file_state_machine(),  # <-- TILFØJ DENNE
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


def get_storage_monitor() -> StorageMonitorService:
    if "storage_monitor" not in _singletons:
        _singletons["storage_monitor"] = StorageMonitorService(
            settings=get_settings(),
            storage_checker=get_storage_checker(),
            event_bus=get_event_bus(),
            network_mount_service=get_network_mount_service(),
            job_queue=None  # Will be set later to avoid circular dependency
        )
        
    # Check if we need to set the job_queue reference after both services exist
    storage_monitor = _singletons["storage_monitor"]
    if storage_monitor._job_queue is None and "job_queue_service" in _singletons:
        storage_monitor._job_queue = _singletons["job_queue_service"]
        
    return storage_monitor


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
        )
    return _singletons["copy_strategy"]


def get_job_processor() -> JobProcessor:
    if "job_processor" not in _singletons:
        settings = get_settings()
        file_repository = get_file_repository()
        job_queue_service = get_job_queue_service()
        copy_strategy = get_copy_strategy()
        space_checker = (
            get_space_checker() if settings.enable_pre_copy_space_check else None
        )
        space_retry_manager = get_space_retry_manager() if space_checker else None
        error_classifier = get_job_error_classifier()
        event_bus = get_event_bus()
        finalization_service = get_job_finalization_service()
        copy_executor = get_job_copy_executor()
        space_manager = get_job_space_manager()

        _singletons["job_processor"] = JobProcessor(
            settings=settings,
            file_repository=file_repository,
            event_bus=event_bus,
            job_queue=job_queue_service,
            copy_strategy=copy_strategy,
            space_checker=space_checker,
            space_retry_manager=space_retry_manager,
            error_classifier=error_classifier,
            finalization_service=finalization_service,
            copy_executor=copy_executor,
            space_manager=space_manager,
        )

    return _singletons["job_processor"]


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


def reset_singletons() -> None:
    global _singletons
    _singletons.clear()

