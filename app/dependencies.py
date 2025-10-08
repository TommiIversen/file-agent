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
    
    Returns:
        FileScannerService instance (oprettes kun én gang)
    """
    if "file_scanner" not in _singletons:
        settings = get_settings()
        state_manager = get_state_manager()
        _singletons["file_scanner"] = FileScannerService(settings, state_manager)
    
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
    Hent FileCopyService singleton instance.
    
    Returns:
        FileCopyService instance (oprettes kun én gang)
    """
    if "file_copier" not in _singletons:
        settings = get_settings()
        state_manager = get_state_manager()
        job_queue_service = get_job_queue_service()
        _singletons["file_copier"] = FileCopyService(settings, state_manager, job_queue_service)
    
    return _singletons["file_copier"]


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
