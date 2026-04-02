"""macOS Network Mounter - SRP compliant with robust mount validation."""

import asyncio
import logging
import os

from .base_mounter import BaseMounter
from .macos_mount_utils import MacOSMountValidator, MacOSNetworkChecker, MacOSMountCleaner


class MacOSMounter(BaseMounter):
    """macOS-specific network mount implementation with robust validation."""

    def __init__(self, mount_point: str | None = None):
        super().__init__()
        self._configured_mount_point = mount_point
        self._mount_validator = MacOSMountValidator()
        self._network_checker = MacOSNetworkChecker()
        self._mount_cleaner = MacOSMountCleaner(self._mount_validator)

    async def attempt_mount(self, share_url: str) -> bool:
        """
        Simple mount attempt - just like the AppleScript that works.
        
        try
            mount volume "smb://svcsk6402@net.dr.dk/nas/videopodcast/SK6402"
        end try
        """
        try:
            expected_mount_point = self.get_mount_point_from_url(share_url)
            
            # Step 1: Quick check if already mounted
            is_mounted, is_accessible = await self.verify_mount_accessible(expected_mount_point)
            if is_mounted and is_accessible:
                logging.info(f"Share already mounted: {share_url} -> {expected_mount_point}")
                return True
            
            # Step 2: Check network connectivity before mount attempt
            if not await self._network_checker.is_network_available(share_url):
                logging.warning(f"Network not available for share {share_url} - skipping mount attempt")
                return False
            
            # Step 3: Simple cleanup - remove any ghost mounts
            ghost_mounts = await self._mount_validator.find_ghost_mounts(expected_mount_point)
            if ghost_mounts:
                logging.info(f"Cleaning up ghost mounts: {ghost_mounts}")
                await self._mount_cleaner.cleanup_ghost_mounts(expected_mount_point)
            
            # Step 4: Clean up any problematic local folder
            await self._mount_cleaner.cleanup_invalid_mount_point(expected_mount_point)
            
            # Step 5: Simple mount - exactly like your AppleScript
            logging.info(f"Attempting macOS mount: {share_url}")

            cmd = ["osascript", "-e", f'mount volume "{share_url}"']

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30.0)
            except asyncio.TimeoutError:
                logging.error(f"Mount operation timed out for {share_url}")
                process.kill()
                await process.wait()
                return False

            # Step 6: Check if mount succeeded
            if process.returncode == 0:
                logging.info(f"Mount command completed for {share_url}")
                
                # Give macOS a moment to complete the mount
                await asyncio.sleep(2)
                
                # Simple check - does the mount point exist and work?
                is_mounted, is_accessible = await self.verify_mount_accessible(expected_mount_point)
                if is_mounted and is_accessible:
                    logging.info(f"Successfully mounted and verified: {share_url} -> {expected_mount_point}")
                    return True
                else:
                    logging.warning(f"Mount command succeeded but mount point not accessible: {expected_mount_point}")
                    return False
            else:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logging.error(f"Mount failed for {share_url}: {error_msg}")
                return False

        except Exception as e:
            logging.error(f"Exception during macOS mount attempt: {e}", exc_info=True)
            return False

    async def verify_mount_accessible(self, local_path: str) -> tuple[bool, bool]:
        """
        Simple check if mount point is accessible.
        Just like 'test -d /Volumes/SK6402 && test -w /Volumes/SK6402'
        """
        try:
            # Check if it exists and is a directory
            if not await asyncio.to_thread(os.path.exists, local_path) or not await asyncio.to_thread(os.path.isdir, local_path):
                return False, False
            
            # Simple access test - try to list contents
            try:
                await asyncio.to_thread(os.listdir, local_path)
                return True, True
            except (OSError, PermissionError):
                return True, False
                
        except Exception as e:
            logging.debug(f"Mount accessibility check failed for {local_path}: {e}")
            return False, False

    def get_platform_name(self) -> str:
        """Get platform name for logging."""
        return "macOS"

    def get_mount_point_from_url(self, share_url: str) -> str:
        """
        Get mount point for share URL.
        
        Uses configured MACOS_MOUNT_POINT if available, otherwise derives from URL.
        """
        try:
            # Prefer configured mount point
            if self._configured_mount_point:
                logging.debug(f"Using configured mount point: {self._configured_mount_point}")
                return self._configured_mount_point
            
            # Fallback: derive from URL
            if "/" in share_url:
                share_name = share_url.split("/")[-1]
            else:
                share_name = share_url

            mount_point = f"/Volumes/{share_name}"
            logging.debug(f"Derived mount point: {mount_point} from URL: {share_url}")
            return mount_point

        except Exception as e:
            logging.error(f"Error getting mount point from URL {share_url}: {e}", exc_info=True)
            return "/Volumes/NetworkShare"
