"""
Dependency Injection for File Transfer Agent.

Centraliseret sted hvor alle services og afhængigheder registreres.
Sikrer singleton pattern og proper dependency management.
"""

import asyncio
from functools import lru_cache
from typing import Dict, Any, Optional

from .config import Settings
from .services.state_manager import StateManager
from .services.file_scanner import FileScannerService
from .services.job_queue import JobQueueService
from .services.file_copier import FileCopyService
from .services.websocket_manager import WebSocketManager
from .services.storage_checker import StorageChecker
from .services.storage_monitor import StorageMonitorService
from .services.network_mount import NetworkMountService
from .services.space_checker import SpaceChecker
from .services.space_retry_manager import SpaceRetryManager

# Global singleton instances
_singletons: Dict[str, Any] = {}


@lru_cache
def get_settings() -> Settings:
    """Hent Settings singleton instance."""
    return Settings()


def get_state_manager() -> StateManager:
    """
    Hent StateManager singleton instance.
    
    Returns:
        StateManager instance (oprettes kun én gang)
    """
    if "state_manager" not in _singletons:
        _singletons["state_manager"] = StateManager()
    
    return _singletons["state_manager"]


def get_file_scanner() -> FileScannerService:
    """
    Hent FileScannerService singleton instance.
    Enhanced: Now injects StorageMonitorService following Central Storage Authority pattern.
    
    Returns:
        FileScannerService instance (oprettes kun én gang)
    """
    if "file_scanner" not in _singletons:
        settings = get_settings()
        state_manager = get_state_manager()
        storage_monitor = get_storage_monitor()  # Inject Central Storage Authority
        _singletons["file_scanner"] = FileScannerService(settings, state_manager, storage_monitor)
    
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
        # JobQueueService will create its own queue internally
        _singletons["job_queue_service"] = JobQueueService(settings, state_manager)
    
    return _singletons["job_queue_service"]


def get_file_copier() -> FileCopyService:
    """
    Hent FileCopyService singleton instance med space checking og resume support.
    
    Returns:
        FileCopyService instance med alle dependencies
    """
    if "file_copier" not in _singletons:
        settings = get_settings()
        state_manager = get_state_manager()
        job_queue_service = get_job_queue_service()
        
        # Space management dependencies (optional for backward compatibility)
        space_checker = get_space_checker() if settings.enable_pre_copy_space_check else None
        space_retry_manager = get_space_retry_manager() if space_checker else None
        
        # Get storage monitor for destination checker integration
        storage_monitor = get_storage_monitor()
        
        _singletons["file_copier"] = FileCopyService(
            settings=settings,
            state_manager=state_manager, 
            job_queue=job_queue_service,
            space_checker=space_checker,
            space_retry_manager=space_retry_manager,
            storage_monitor=storage_monitor,
            enable_resume=settings.enable_secure_resume  # Enable resume based on settings
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
            settings=settings,
            storage_monitor=storage_monitor
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
            settings=settings,
            state_manager=state_manager
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
        # Note: storage_monitor will be set later to avoid circular dependency
        _singletons["websocket_manager"] = WebSocketManager(state_manager)
    
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
            job_queue=job_queue_service  # Enable universal recovery
        )
        
        # Set storage_monitor reference in WebSocketManager to avoid circular dependency
        websocket_manager._storage_monitor = _singletons["storage_monitor"]
    
    return _singletons["storage_monitor"]


async def get_job_queue() -> Optional[asyncio.Queue]:
    """
    Hent job queue singleton instance.
    
    Returns:
        asyncio.Queue instance for file job processing eller None hvis ikke oprettet
    """
    # Get queue from JobQueueService to ensure single instance
    job_queue_service = get_job_queue_service()
    return job_queue_service.job_queue


def reset_singletons() -> None:
    """
    Reset alle singletons - primært til test formål.
    
    VIGTIGT: Kun til brug i tests!
    """
    global _singletons
    _singletons.clear()
