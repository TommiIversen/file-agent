"""
Dependency Injection for File Transfer Agent.

Centraliseret sted hvor alle services og afhængigheder registreres.
Sikrer singleton pattern og proper dependency management.
"""

import asyncio
from functools import lru_cache
from typing import Dict, Any

from .config import Settings
from .services.state_manager import StateManager
from .services.file_scanner import FileScannerService

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


async def get_job_queue() -> asyncio.Queue:
    """
    Hent job queue singleton instance.
    
    Returns:
        asyncio.Queue instance for file job processing
    """
    if "job_queue" not in _singletons:
        _singletons["job_queue"] = asyncio.Queue()
    
    return _singletons["job_queue"]


def reset_singletons() -> None:
    """
    Reset alle singletons - primært til test formål.
    
    VIGTIGT: Kun til brug i tests!
    """
    global _singletons
    _singletons.clear()
