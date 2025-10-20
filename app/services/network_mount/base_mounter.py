"""Abstract Base Mounter - SRP compliant interface definition."""

from abc import ABC, abstractmethod
from typing import Tuple


class BaseMounter(ABC):
    """Abstract base class for platform-specific mount operations."""

    def __init__(self):
        pass

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
