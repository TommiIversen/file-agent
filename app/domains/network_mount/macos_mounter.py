"""macOS Network Mounter - SRP compliant with robust mount validation."""

import asyncio
import logging
from typing import Tuple

import aiofiles.os

from .base_mounter import BaseMounter
from .macos_mount_utils import MacOSMountValidator, MacOSNetworkChecker, MacOSMountCleaner


class MacOSMounter(BaseMounter):
    """macOS-specific network mount implementation with robust validation."""

    def __init__(self, mount_point: str = None):
        super().__init__()
        self._configured_mount_point = mount_point
        self._mount_validator = MacOSMountValidator()
        self._network_checker = MacOSNetworkChecker()
        self._mount_cleaner = MacOSMountCleaner(self._mount_validator)

    async def attempt_mount(self, share_url: str) -> bool:
        """
        Attempt to mount network share with robust validation and cleanup.
        
        Includes network connectivity check, cleanup of invalid states,
        and verification that the resulting mount is actually a network mount.
        """
        try:
            expected_mount_point = self.get_mount_point_from_url(share_url)
            
            # Step 1: Check network connectivity first - test our specific share host
            if not await self._network_checker.is_network_available(share_url):
                logging.warning(f"Network not available for share {share_url} - skipping mount attempt")
                return False
            
            # Step 2: Clean up any existing problematic state
            logging.info(f"Cleaning up any invalid state at mount point: {expected_mount_point}")
            
            # Clean up any ghost mounts first
            cleaned_ghosts = await self._mount_cleaner.cleanup_ghost_mounts(expected_mount_point)
            if cleaned_ghosts:
                logging.info(f"Cleaned up ghost mounts: {cleaned_ghosts}")
            
            # Clean up invalid local folder at mount point
            cleanup_success = await self._mount_cleaner.cleanup_invalid_mount_point(expected_mount_point)
            if not cleanup_success:
                logging.error(f"Failed to clean up invalid state at {expected_mount_point}")
                return False
                
            # Step 3: Check if already properly mounted
            is_mounted, is_accessible = await self.verify_mount_accessible(expected_mount_point)

            if is_mounted and is_accessible:
                logging.info(f"Share already mounted and accessible: {share_url} -> {expected_mount_point}")
                return True
            elif is_mounted and not is_accessible:
                logging.warning(f"Share mounted but not accessible: {share_url} -> {expected_mount_point}")
                # Continue with mount attempt - might fix accessibility issues

            # Step 4: Attempt the actual mount
            logging.info(f"Attempting macOS mount: {share_url}")

            cmd = ["osascript", "-e", f'mount volume "{share_url}"']

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15.0)
            except asyncio.TimeoutError:
                logging.error(f"Mount operation timed out for {share_url}")
                process.kill()
                await process.wait()
                return False

            # Step 5: Check mount result
            if process.returncode == 0:
                logging.info(f"Mount command completed for {share_url}")
                
                # Step 6: Verify the mount is actually a real network mount
                await asyncio.sleep(2)  # Give macOS time to complete the mount
                
                is_real_mount = await self._mount_validator.is_real_network_mount(expected_mount_point)
                if is_real_mount:
                    logging.info(f"Successfully verified network mount: {share_url} -> {expected_mount_point}")
                    return True
                else:
                    # Check if macOS created a ghost mount instead
                    ghost_mounts = await self._mount_validator.find_ghost_mounts(expected_mount_point)
                    if ghost_mounts:
                        logging.error(f"Mount created ghost mount instead: {ghost_mounts}. Expected: {expected_mount_point}")
                        # Clean up the ghost mounts
                        await self._mount_cleaner.cleanup_ghost_mounts(expected_mount_point)
                    else:
                        logging.error(f"Mount command succeeded but no valid network mount found at {expected_mount_point}")
                    return False
                    
            else:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logging.error(f"Mount failed for {share_url}: {error_msg}")
                return False

        except Exception as e:
            logging.error(f"Exception during macOS mount attempt: {e}")
            return False

    async def verify_mount_accessible(self, local_path: str) -> Tuple[bool, bool]:
        """
        Verify if mount point is a real network mount and accessible.
        
        Returns (is_mounted, is_accessible).
        Uses robust validation to distinguish between real network mounts
        and local folders that shouldn't exist at mount points.
        """
        try:
            # First check if path exists at all
            try:
                path_exists = await asyncio.wait_for(
                    aiofiles.os.path.exists(local_path), timeout=5.0
                )
                if not path_exists:
                    logging.debug(f"Mount point does not exist: {local_path}")
                    return False, False

                path_is_dir = await asyncio.wait_for(
                    aiofiles.os.path.isdir(local_path), timeout=5.0
                )
                if not path_is_dir:
                    logging.debug(f"Mount point is not a directory: {local_path}")
                    return False, False

            except asyncio.TimeoutError:
                logging.warning(f"Path check timed out for: {local_path}")
                return False, False

            # Critical check: Is this a real network mount or just a local folder?
            is_real_mount = await self._mount_validator.is_real_network_mount(local_path)
            
            if not is_real_mount:
                # Path exists but is not a real network mount
                logging.warning(f"Path exists but is not a real network mount: {local_path}")
                
                # Check if it's a problematic local folder
                is_local = await self._mount_validator.is_local_folder_at_mount_point(local_path)
                if is_local:
                    logging.error(f"DANGER: Found local folder at network mount point: {local_path}")
                    return True, False  # Exists but not accessible as network mount
                
                return False, False

            # It's a real network mount, now test accessibility
            try:
                process = await asyncio.create_subprocess_exec(
                    "ls",
                    local_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                try:
                    _, stderr = await asyncio.wait_for(
                        process.communicate(), timeout=10.0
                    )
                except asyncio.TimeoutError:
                    logging.warning(f"ls command timed out for network mount: {local_path}")
                    process.kill()
                    await process.wait()
                    return True, False  # Mounted but not accessible

                if process.returncode == 0:
                    logging.debug(f"Network mount accessible: {local_path}")
                    return True, True
                else:
                    error_msg = stderr.decode() if stderr else "Unknown error"
                    logging.debug(f"Network mount not accessible: {local_path} - {error_msg}")
                    return True, False

            except Exception as e:
                logging.debug(f"Error testing network mount accessibility: {e}")
                return True, False

        except Exception as e:
            logging.error(f"Exception during mount verification: {e}")
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
            logging.error(f"Error getting mount point from URL {share_url}: {e}")
            return "/Volumes/NetworkShare"
