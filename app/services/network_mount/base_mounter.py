"""Abstract Base Mounter - SRP compliant interface definition."""

from abc import ABC, abstractmethod
from typing import Tuple
from ...logging_config import get_app_logger


class BaseMounter(ABC):
    """Abstract base class for platform-specific mount operations. SRP: Interface definition ONLY."""
    
    def __init__(self):
        self._logger = get_app_logger()
    
    @abstractmethod
    async def attempt_mount(self, share_url: str) -> bool:
        """Attempt to mount network share."""
        pass
    
    @abstractmethod
    async def verify_mount_accessible(self, local_path: str) -> Tuple[bool, bool]:
        """Verify if mount is accessible. Returns (is_mounted, is_accessible)."""
        pass
    
    @abstractmethod
    def get_platform_name(self) -> str:
        """Get platform name for logging."""
        pass