"""Network Mount Service - SRP compliant orchestrator."""

from typing import Optional

from .platform_factory import PlatformFactory, UnsupportedPlatformError
from .base_mounter import BaseMounter
from .mount_config import MountConfigHandler
from ...config import Settings
from ...logging_config import get_app_logger


class NetworkMountService:
    """Orchestrates network mount operations across platforms. SRP: Mount orchestration ONLY."""
    
    def __init__(self, settings: Settings):
        self._logger = get_app_logger()
        self._config = MountConfigHandler(settings)
        self._platform_factory = PlatformFactory()
        self._mounter: Optional[BaseMounter] = None
        self._initialize_mounter()
    
    def _initialize_mounter(self) -> None:
        """Initialize platform-specific mounter."""
        try:
            platform_name = self._platform_factory.detect_platform()
            self._logger.info(f"Detected platform: {platform_name}")
            
            if platform_name == "windows":
                from .windows_mounter import WindowsMounter
                self._mounter = WindowsMounter(drive_letter=self._config.get_windows_drive_letter())
            else:
                self._mounter = self._platform_factory.create_mounter()
            
            self._logger.info(f"Initialized {self._mounter.get_platform_name()} mounter")
            
        except (UnsupportedPlatformError, Exception) as e:
            self._logger.error(f"Error initializing network mounter: {e}")
            self._mounter = None
    
    async def ensure_mount_available(self, share_url: str, local_path: str) -> bool:
        """Ensure network mount is available and accessible. Called by StorageMonitorService every 30 seconds."""
        if not self._config.is_auto_mount_enabled() or not self._mounter or not share_url:
            return False
        
        try:
            is_mounted, is_accessible = await self._mounter.verify_mount_accessible(local_path)
            
            if is_mounted and is_accessible:
                return True
            if is_mounted and not is_accessible:
                return False
            
            # Attempt mounting
            if await self._mounter.attempt_mount(share_url):
                is_mounted, is_accessible = await self._mounter.verify_mount_accessible(local_path)
                return is_mounted and is_accessible
            return False
            
        except Exception as e:
            self._logger.error(f"Error ensuring mount availability: {e}")
            return False
    
    async def verify_mount_accessible(self, local_path: str) -> bool:
        """Verify if mount point is accessible."""
        if not self._mounter:
            return False
        try:
            is_mounted, is_accessible = await self._mounter.verify_mount_accessible(local_path)
            return is_mounted and is_accessible
        except Exception as e:
            self._logger.error(f"Error verifying mount accessibility: {e}")
            return False
    
    def is_network_mount_configured(self) -> bool:
        """Check if network mounting is configured and enabled."""
        return self._config.is_network_mount_configured() and self._mounter is not None
    
    def get_network_share_url(self) -> Optional[str]:
        """Get configured network share URL."""
        return self._config.get_network_share_url()
    
    def get_expected_mount_point(self) -> Optional[str]:
        """Get expected mount point for configured share."""
        if not self._mounter:
            return None
        share_url = self.get_network_share_url()
        if not share_url:
            return None
        try:
            return self._mounter.get_mount_point_from_url(share_url) if hasattr(self._mounter, 'get_mount_point_from_url') else None
        except Exception as e:
            self._logger.error(f"Error getting expected mount point: {e}")
            return None
    
    def get_platform_info(self) -> dict:
        """Get platform and mounter information."""
        platform_name = "unknown"
        mounter_available = bool(self._mounter)
        
        if self._mounter:
            platform_name = self._mounter.get_platform_name()
        else:
            try:
                platform_name = self._platform_factory.detect_platform()
            except Exception:
                pass
        
        config_info = self._config.get_platform_config()
        config_info.update({
            "platform": platform_name,
            "mounter_available": mounter_available,
            "mount_service_ready": self.is_network_mount_configured()
        })
        return config_info