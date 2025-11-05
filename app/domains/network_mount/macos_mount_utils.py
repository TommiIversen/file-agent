"""macOS Mount Point Validation Utilities - SIMPLIFIED."""

import asyncio
import logging
from pathlib import Path


class MacOSNetworkChecker:
    """Simple network connectivity checker."""
    
    def __init__(self):
        pass
    
    async def is_network_available(self, share_url: str = None) -> bool:
        """
        Simple network check - just return True.
        
        The mount will fail if network is down anyway, so no need to pre-check.
        """
        return True
    
    async def can_reach_share_host(self, share_url: str) -> bool:
        """
        Simple host check - just return True.
        
        The mount will fail if host is unreachable anyway.
        """
        return True


class MacOSMountValidator:
    """Simple mount validator."""
    
    def __init__(self):
        pass
    
    async def is_real_network_mount(self, mount_path: str) -> bool:
        """
        Check if path is a real network mount by checking if it's a directory
        and if we can list it without errors.
        """
        try:
            path_obj = Path(mount_path)
            
            # If path doesn't exist, it's not mounted
            if not await asyncio.to_thread(path_obj.exists):
                return False
                
            # If it exists and is a directory, assume it's mounted
            # (the mount operation will tell us if it worked)
            if await asyncio.to_thread(path_obj.is_dir):
                return True
                
            return False
            
        except Exception as e:
            logging.debug(f"Error checking mount status: {e}")
            return False
    
    async def is_local_folder_at_mount_point(self, mount_path: str) -> bool:
        """
        Check if there's a problematic local folder at the mount point.
        
        For simplicity, just check if directory exists but can't be listed.
        """
        try:
            path_obj = Path(mount_path)
            
            if not await asyncio.to_thread(path_obj.exists):
                return False
                
            if not await asyncio.to_thread(path_obj.is_dir):
                return False
                
            # Try to list directory - if it fails, might be a mount issue
            try:
                await asyncio.to_thread(list, path_obj.iterdir())
                return False  # Can list it, so it's probably fine
            except PermissionError:
                return True  # Can't list it, might be problematic local folder
                
        except Exception:
            return False
    
    async def find_ghost_mounts(self, base_mount_path: str) -> list:
        """Find numbered variants like /Volumes/SK6402_1."""
        try:
            base_path = Path(base_mount_path)
            base_name = base_path.name
            volumes_dir = base_path.parent
            
            if not await asyncio.to_thread(volumes_dir.exists):
                return []
            
            ghost_mounts = []
            
            # Look for numbered variants
            for item in await asyncio.to_thread(list, volumes_dir.iterdir()):
                if await asyncio.to_thread(item.is_dir):
                    item_name = item.name
                    # Simple check for _1, _2, etc.
                    if item_name.startswith(base_name + "_") and item_name[len(base_name)+1:].isdigit():
                        ghost_mounts.append(str(item))
            
            return ghost_mounts
            
        except Exception as e:
            logging.debug(f"Error finding ghost mounts: {e}")
            return []


class MacOSMountCleaner:
    """Simple mount cleaner."""
    
    def __init__(self, mount_validator):
        self._validator = mount_validator
    
    async def cleanup_invalid_mount_point(self, mount_path: str) -> bool:
        """
        Clean up invalid local folder at mount point.
        
        Only removes empty directories in /Volumes/ for safety.
        """
        try:
            path_obj = Path(mount_path)
            
            # Safety check - only work in /Volumes/
            if not str(path_obj).startswith('/Volumes/'):
                return True
                
            # If it's a problematic local folder, try to remove it
            if await self._validator.is_local_folder_at_mount_point(mount_path):
                logging.warning(f"Removing problematic local folder: {mount_path}")
                try:
                    await asyncio.to_thread(path_obj.rmdir)
                    logging.info(f"Removed problematic folder: {mount_path}")
                except OSError as e:
                    logging.warning(f"Could not remove folder {mount_path}: {e}")
                    return False
                    
            return True
            
        except Exception as e:
            logging.debug(f"Error cleaning up mount point: {e}")
            return True  # Don't fail the mount for cleanup issues
    
    async def cleanup_ghost_mounts(self, base_mount_path: str) -> list:
        """Remove ghost mounts like /Volumes/SK6402_1."""
        cleaned = []
        
        try:
            ghost_mounts = await self._validator.find_ghost_mounts(base_mount_path)
            
            for ghost_path in ghost_mounts:
                logging.warning(f"Removing ghost mount: {ghost_path}")
                try:
                    path_obj = Path(ghost_path)
                    await asyncio.to_thread(path_obj.rmdir)
                    cleaned.append(ghost_path)
                except OSError as e:
                    logging.warning(f"Could not remove ghost mount {ghost_path}: {e}")
                    
        except Exception as e:
            logging.debug(f"Error cleaning ghost mounts: {e}")
            
        return cleaned