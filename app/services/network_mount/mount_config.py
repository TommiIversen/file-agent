"""Mount Configuration Handler - SRP compliant configuration management."""

from typing import Optional
from ...config import Settings



class MountConfigHandler:
    """Handles network mount configuration validation and access. SRP: Configuration management ONLY."""
    
    def __init__(self, settings: Settings):
        self._settings = settings
        
    
    def is_auto_mount_enabled(self) -> bool:
        """Check if auto-mount is enabled in settings."""
        return getattr(self._settings, 'enable_auto_mount', False)
    
    def get_network_share_url(self) -> Optional[str]:
        """Get configured network share URL."""
        return getattr(self._settings, 'network_share_url', None)
    
    def get_windows_drive_letter(self) -> Optional[str]:
        """Get configured Windows drive letter."""
        return getattr(self._settings, 'windows_drive_letter', None)
    
    def is_network_mount_configured(self) -> bool:
        """Check if network mounting is fully configured and enabled."""
        return (
            self.is_auto_mount_enabled() and
            bool(self.get_network_share_url())
        )
    
    def get_platform_config(self) -> dict:
        """Get platform-specific configuration."""
        return {
            "auto_mount_enabled": self.is_auto_mount_enabled(),
            "network_share_configured": bool(self.get_network_share_url()),
            "share_url": self.get_network_share_url(),
            "windows_drive_letter": self.get_windows_drive_letter()
        }
