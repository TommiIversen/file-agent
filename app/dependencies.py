"""
Dependency Injection for File Transfer Agent.

Centraliseret sted hvor alle services og afhængigheder registreres.
Sikrer singleton pattern og proper dependency management.
"""

import asyncio
from functools import lru_cache
from typing import Dict, Any, Optional

from app.core.events.event_bus import DomainEventBus

from .config import Settings
from .services.consumer.job_error_classifier import JobErrorClassifier
from .services.consumer.job_processor import JobProcessor
from .services.copy.file_copy_executor import FileCopyExecutor
from .services.copy_strategies import GrowingFileCopyStrategy
from .services.file_copier import FileCopierService
from .services.job_queue import JobQueueService
from .services.network_mount import NetworkMountService
from .services.scanner.file_scanner_service import FileScannerService
from .services.space_checker import SpaceChecker
from .services.space_retry_manager import SpaceRetryManager
from .services.state_manager import StateManager
from .services.storage_checker import StorageChecker
from .services.storage_monitor import StorageMonitorService
from .services.websocket_manager import WebSocketManager


from app.core.cqrs.command_bus import CommandBus
from app.core.cqrs.query_bus import QueryBus

from app.domains.directory_browsing.service import DirectoryScannerService
from app.domains.directory_browsing.queries import (
    ScanSourceDirectoryQuery, ScanDestinationDirectoryQuery, 
    ScanCustomDirectoryQuery, GetScannerInfoQuery
)
from app.domains.directory_browsing.handlers import (
    ScanSourceDirectoryHandler, ScanDestinationDirectoryHandler, 
    ScanCustomDirectoryHandler, GetScannerInfoHandler
)


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
    """
    Hent DomainEventBus singleton instance.

    Returns:
        DomainEventBus instance (oprettes kun én gang)
    """

    if "event_bus" not in _singletons:
        _singletons["event_bus"] = DomainEventBus()

    return _singletons["event_bus"]


def get_state_manager() -> StateManager:
    """
    Hent StateManager singleton instance.

    Returns:
        StateManager instance (oprettes kun én gang)
    """
    if "state_manager" not in _singletons:
        settings = get_settings()
        event_bus = get_event_bus()
        _singletons["state_manager"] = StateManager(
            cooldown_minutes=settings.space_error_cooldown_minutes, event_bus=event_bus
        )

    return _singletons["state_manager"]


def get_file_scanner() -> FileScannerService:
    """
    Hent FileScannerService singleton instance.
    Enhanced: Now injects StorageMonitorService following Central Storage Authority pattern
    and WebSocketManager for proper dependency injection.

    Returns:
        FileScannerService instance (oprettes kun én gang)
    """
    if "file_scanner" not in _singletons:
        settings = get_settings()
        state_manager = get_state_manager()
        storage_monitor = get_storage_monitor()  # Inject Central Storage Authority
        websocket_manager = get_websocket_manager()  # Inject WebSocket manager
        event_bus = get_event_bus()
        _singletons["file_scanner"] = FileScannerService(
            settings,
            state_manager,
            storage_monitor,
            websocket_manager,
            event_bus=event_bus,
        )

    return _singletons["file_scanner"]


def get_job_queue_service() -> JobQueueService:
    """
    Hent JobQueueService singleton instance.

    Returns:
        JobQueueService instance (oprettes kun én gang)
    """
    if "job_queue_service" not in _singletons:
        settings = get_settings()
        state_manager = get_state_manager()
        event_bus = get_event_bus()
        # JobQueueService will create its own queue internally
        _singletons["job_queue_service"] = JobQueueService(
            settings, state_manager, event_bus=event_bus
        )

    return _singletons["job_queue_service"]


def get_file_copier() -> FileCopierService:
    """
    Hent FileCopierService singleton instance med JobProcessor dependency.

    Returns:
        FileCopierService instance med alle dependencies
    """
    if "file_copier" not in _singletons:
        settings = get_settings()
        state_manager = get_state_manager()
        job_queue_service = get_job_queue_service()
        job_processor = get_job_processor()

        _singletons["file_copier"] = FileCopierService(
            settings=settings,
            state_manager=state_manager,
            job_queue=job_queue_service,
            job_processor=job_processor,
        )

    return _singletons["file_copier"]


def get_space_checker() -> SpaceChecker:
    """
    Hent SpaceChecker singleton instance.

    Returns:
        SpaceChecker instance for pre-flight space checking
    """
    if "space_checker" not in _singletons:
        settings = get_settings()
        storage_monitor = get_storage_monitor()

        _singletons["space_checker"] = SpaceChecker(
            settings=settings, storage_monitor=storage_monitor
        )

    return _singletons["space_checker"]


def get_space_retry_manager() -> SpaceRetryManager:
    """
    Hent SpaceRetryManager singleton instance.

    Returns:
        SpaceRetryManager instance for space retry logic
    """
    if "space_retry_manager" not in _singletons:
        settings = get_settings()
        state_manager = get_state_manager()

        _singletons["space_retry_manager"] = SpaceRetryManager(
            settings=settings, state_manager=state_manager
        )

    return _singletons["space_retry_manager"]


def get_websocket_manager() -> WebSocketManager:
    """
    Hent WebSocketManager singleton instance.

    Returns:
        WebSocketManager instance (oprettes kun én gang)
    """
    if "websocket_manager" not in _singletons:
        state_manager = get_state_manager()
        event_bus = get_event_bus()
        # Note: storage_monitor will be set later to avoid circular dependency
        ws_manager = WebSocketManager(state_manager, event_bus=event_bus)

        # Scanner status will be initialized later to avoid circular dependency
        _singletons["websocket_manager"] = ws_manager

    return _singletons["websocket_manager"]


def get_storage_checker() -> StorageChecker:
    """
    Hent StorageChecker singleton instance.

    Returns:
        StorageChecker instance (oprettes kun én gang)
    """
    if "storage_checker" not in _singletons:
        settings = get_settings()
        _singletons["storage_checker"] = StorageChecker(
            test_file_prefix=settings.storage_test_file_prefix
        )

    return _singletons["storage_checker"]


def get_network_mount_service() -> NetworkMountService:
    """
    Hent NetworkMountService singleton instance.

    Returns:
        NetworkMountService instance (oprettes kun én gang)
    """
    if "network_mount_service" not in _singletons:
        settings = get_settings()
        _singletons["network_mount_service"] = NetworkMountService(settings)

    return _singletons["network_mount_service"]


def get_storage_monitor() -> StorageMonitorService:
    """
    Hent StorageMonitorService singleton instance.
    Enhanced: Now integrates with NetworkMountService for automatic network mount handling
    and JobQueueService for universal recovery system.

    Returns:
        StorageMonitorService instance (oprettes kun én gang)
    """
    if "storage_monitor" not in _singletons:
        settings = get_settings()
        storage_checker = get_storage_checker()
        websocket_manager = get_websocket_manager()
        network_mount_service = get_network_mount_service()  # Phase 2 integration
        job_queue_service = get_job_queue_service()  # Universal recovery system

        _singletons["storage_monitor"] = StorageMonitorService(
            settings=settings,
            storage_checker=storage_checker,
            websocket_manager=websocket_manager,
            network_mount_service=network_mount_service,
            job_queue=job_queue_service,  # Enable universal recovery
        )

        # Set storage_monitor reference in WebSocketManager to avoid circular dependency
        websocket_manager._storage_monitor = _singletons["storage_monitor"]

        # Set storage_monitor reference in JobQueueService for network checking
        job_queue_service.storage_monitor = _singletons["storage_monitor"]

    return _singletons["storage_monitor"]


def get_job_error_classifier() -> JobErrorClassifier:
    """
    Hent JobErrorClassifier singleton instance.

    Returns:
        JobErrorClassifier instance (oprettes kun én gang)
    """
    if "job_error_classifier" not in _singletons:
        storage_monitor = get_storage_monitor()
        _singletons["job_error_classifier"] = JobErrorClassifier(storage_monitor)

    return _singletons["job_error_classifier"]


def get_file_copy_executor() -> FileCopyExecutor:
    """
    Hent FileCopyExecutor singleton instance.
    """
    if "file_copy_executor" not in _singletons:
        settings = get_settings()
        _singletons["file_copy_executor"] = FileCopyExecutor(settings)
    return _singletons["file_copy_executor"]


def get_copy_strategy() -> GrowingFileCopyStrategy:
    """
    Hent GrowingFileCopyStrategy singleton instance.
    """
    if "copy_strategy" not in _singletons:
        settings = get_settings()
        state_manager = get_state_manager()
        file_copy_executor = get_file_copy_executor()
        event_bus = get_event_bus()
        _singletons["copy_strategy"] = GrowingFileCopyStrategy(
            settings, state_manager, file_copy_executor, event_bus=event_bus
        )
    return _singletons["copy_strategy"]


def get_job_processor() -> JobProcessor:
    """
    Hent JobProcessor singleton instance.

    Returns:
        JobProcessor instance med alle dependencies
    """
    if "job_processor" not in _singletons:
        settings = get_settings()
        state_manager = get_state_manager()
        job_queue_service = get_job_queue_service()
        copy_strategy = get_copy_strategy()
        space_checker = (
            get_space_checker() if settings.enable_pre_copy_space_check else None
        )
        space_retry_manager = get_space_retry_manager() if space_checker else None
        error_classifier = get_job_error_classifier()
        event_bus = get_event_bus()

        _singletons["job_processor"] = JobProcessor(
            settings=settings,
            state_manager=state_manager,
            job_queue=job_queue_service,
            copy_strategy=copy_strategy,
            space_checker=space_checker,
            space_retry_manager=space_retry_manager,
            error_classifier=error_classifier,
            event_bus=event_bus,
        )

    return _singletons["job_processor"]


def get_directory_scanner() -> DirectoryScannerService:
    """
    Hent DirectoryScannerService singleton instance.

    SRP compliant service for directory scanning with async timeout protection.
    Only depends on Settings - no other service dependencies.

    Returns:
        DirectoryScannerService instance (oprettes kun én gang)
    """
    if "directory_scanner" not in _singletons:
        settings = get_settings()
        _singletons["directory_scanner"] = DirectoryScannerService(settings)

    return _singletons["directory_scanner"]


async def get_job_queue() -> Optional[asyncio.Queue]:
    """
    Hent job queue singleton instance.

    Returns:
        asyncio.Queue instance for file job processing eller None hvis ikke oprettet
    """
    # Get queue from JobQueueService to ensure single instance
    job_queue_service = get_job_queue_service()
    return job_queue_service.job_queue




def get_directory_scanner() -> DirectoryScannerService:
    if "directory_scanner" not in _singletons:
        _singletons["directory_scanner"] = DirectoryScannerService(get_settings())
    return _singletons["directory_scanner"]

# 3. Registrer alle handlers (dette kan gøres i en startup-funktion)
def register_handlers():
    query_bus = get_query_bus()
    scanner_service = get_directory_scanner()

    # Registrer Directory Browsing Handlers
    query_bus.register(
        ScanSourceDirectoryQuery,
        ScanSourceDirectoryHandler(scanner_service).handle
    )
    query_bus.register(
        ScanDestinationDirectoryQuery,
        ScanDestinationDirectoryHandler(scanner_service).handle
    )
    query_bus.register(
        ScanCustomDirectoryQuery,
        ScanCustomDirectoryHandler(scanner_service).handle
    )
    query_bus.register(
        GetScannerInfoQuery,
        GetScannerInfoHandler(scanner_service).handle
    )

register_handlers()


def reset_singletons() -> None:
    """
    Reset alle singletons - primært til test formål.

    VIGTIGT: Kun til brug i tests!
    """
    global _singletons
    _singletons.clear()

