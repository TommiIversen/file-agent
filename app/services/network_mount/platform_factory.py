"""Platform Factory - SRP compliant platform detection and mounter creation."""

import platform
from .base_mounter import BaseMounter
from ...logging_config import get_app_logger


class UnsupportedPlatformError(Exception):
    """Raised when platform is not supported for network mounting."""
    pass


class PlatformFactory:
    """Factory for creating platform-specific mount implementations. SRP: Platform detection/creation ONLY."""
    
    def __init__(self):
        self._logger = get_app_logger()
    
    def detect_platform(self) -> str:
        """Detect current platform. Returns: macos, windows, or linux."""
        system = platform.system().lower()
        
        if system == "darwin":
            return "macos"
        elif system == "windows":
            return "windows"
        elif system == "linux":
            return "linux"
        else:
            raise UnsupportedPlatformError(f"Platform {system} not supported for network mounting")
    
    def create_mounter(self) -> BaseMounter:
        """Create platform-specific mounter instance."""
        platform_name = self.detect_platform()
        
        if platform_name == "macos":
            from .macos_mounter import MacOSMounter
            return MacOSMounter()
        elif platform_name == "windows":
            from .windows_mounter import WindowsMounter
            return WindowsMounter()
        else:
            raise UnsupportedPlatformError(f"No mounter implementation for platform: {platform_name}")