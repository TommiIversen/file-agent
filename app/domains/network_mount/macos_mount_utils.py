"""macOS Mount Point Validation Utilities - SRP compliant."""

import asyncio
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional


class MacOSMountValidator:
    """Validates macOS mount points and detects network mounts vs local folders."""
    
    def __init__(self):
        pass
    
    async def is_real_network_mount(self, mount_path: str) -> bool:
        """
        Check if path is a real network mount (not just a local folder).
        
        Uses 'mount' command to verify actual mount status.
        Returns True only if it's an actual mounted network filesystem.
        """
        try:
            # Use mount command to get all mounted filesystems
            process = await asyncio.create_subprocess_exec(
                "mount",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5.0)
            
            if process.returncode != 0:
                logging.error(f"Mount command failed: {stderr.decode() if stderr else 'Unknown error'}")
                return False
                
            mount_output = stdout.decode()
            
            # Check if our path is in the mount output as a network mount
            for line in mount_output.splitlines():
                if mount_path in line:
                    # Look for network filesystem indicators
                    if any(fs_type in line.lower() for fs_type in ['smbfs', 'nfs', 'afp', 'cifs']):
                        logging.debug(f"Found network mount: {line.strip()}")
                        return True
                    else:
                        logging.warning(f"Found local mount at network path: {line.strip()}")
                        return False
            
            # Path not found in mount output - not mounted
            logging.debug(f"Path not found in mount output: {mount_path}")
            return False
            
        except asyncio.TimeoutError:
            logging.error(f"Mount command timed out while checking {mount_path}")
            return False
        except Exception as e:
            logging.error(f"Error checking mount status for {mount_path}: {e}")
            return False
    
    async def get_mount_info(self, mount_path: str) -> Optional[Dict[str, str]]:
        """
        Get detailed mount information for a path.
        
        Returns dict with mount details or None if not mounted.
        """
        try:
            process = await asyncio.create_subprocess_exec(
                "mount",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5.0)
            
            if process.returncode != 0:
                return None
                
            mount_output = stdout.decode()
            
            for line in mount_output.splitlines():
                if mount_path in line:
                    # Parse mount line: "//server/share on /Volumes/share (smbfs, ...)"
                    match = re.match(r'^(.+?)\s+on\s+(.+?)\s+\((.+?)\)$', line.strip())
                    if match:
                        return {
                            'source': match.group(1),
                            'mount_point': match.group(2),
                            'filesystem': match.group(3).split(',')[0].strip(),
                            'options': match.group(3),
                            'raw_line': line.strip()
                        }
            
            return None
            
        except Exception as e:
            logging.error(f"Error getting mount info for {mount_path}: {e}")
            return None
    
    async def is_local_folder_at_mount_point(self, mount_path: str) -> bool:
        """
        Check if there's a local folder at the expected mount point.
        
        This is dangerous - means the mount failed but a local folder exists.
        """
        try:
            path_obj = Path(mount_path)
            
            # Check if path exists as a directory
            if not (await asyncio.to_thread(path_obj.exists) and 
                   await asyncio.to_thread(path_obj.is_dir)):
                return False
            
            # If it exists but is not a real network mount, it's a local folder
            is_network = await self.is_real_network_mount(mount_path)
            return not is_network
            
        except Exception as e:
            logging.error(f"Error checking if {mount_path} is local folder: {e}")
            return False
    
    async def find_ghost_mounts(self, base_mount_path: str) -> List[str]:
        """
        Find 'ghost mounts' like /Volumes/SK6402_1, /Volumes/SK6402_2, etc.
        
        These are created when macOS can't mount to the preferred name.
        """
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
                    # Match pattern like "SK6402_1", "SK6402_2", etc.
                    if re.match(f'^{re.escape(base_name)}_\\d+$', item_name):
                        ghost_mounts.append(str(item))
            
            return ghost_mounts
            
        except Exception as e:
            logging.error(f"Error finding ghost mounts for {base_mount_path}: {e}")
            return []


class MacOSNetworkChecker:
    """Checks network connectivity before attempting mounts."""
    
    def __init__(self):
        pass
    
    async def is_network_available(self, share_url: str = None) -> bool:
        """
        Check if network is available for our share.
        
        If share_url is provided, tests connectivity to that share host.
        Otherwise does a basic local network connectivity test.
        """
        try:
            if share_url:
                # Test connectivity to our actual share host
                return await self.can_reach_share_host(share_url)
            else:
                # Fallback: test local network gateway connectivity
                # Try to ping the default gateway
                process = await asyncio.create_subprocess_exec(
                    "route", "get", "default",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, _ = await asyncio.wait_for(process.communicate(), timeout=3.0)
                
                if process.returncode != 0:
                    logging.debug("Could not get default route")
                    return False
                
                # Extract gateway IP from route output
                route_output = stdout.decode()
                gateway_ip = None
                for line in route_output.splitlines():
                    if "gateway:" in line.lower():
                        parts = line.split()
                        if len(parts) >= 2:
                            gateway_ip = parts[1]
                            break
                
                if not gateway_ip:
                    logging.debug("Could not extract gateway IP")
                    return False
                
                # Ping the gateway
                process = await asyncio.create_subprocess_exec(
                    "ping", "-c", "1", "-W", "2000", gateway_ip,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                _, _ = await asyncio.wait_for(process.communicate(), timeout=5.0)
                
                return process.returncode == 0
            
        except Exception as e:
            logging.warning(f"Network check failed: {e}")
            return False
    
    async def can_reach_share_host(self, share_url: str) -> bool:
        """
        Check if we can reach the host from the share URL.
        
        Uses DNS lookup first (faster) then ping as backup.
        """
        try:
            # Extract hostname from SMB URL
            # Format: smb://svcsk6402@net.dr.dk/nas/videopodcast/SK6402
            if not share_url.startswith('smb://'):
                logging.warning(f"Unsupported share URL format: {share_url}")
                return False
            
            # Remove smb:// prefix
            url_part = share_url[6:]
            
            # Extract hostname (handle username@ prefix)
            if '@' in url_part:
                url_part = url_part.split('@', 1)[1]
            
            # Extract hostname (before first /)
            hostname = url_part.split('/')[0]
            
            if not hostname:
                logging.error(f"Could not extract hostname from share URL: {share_url}")
                return False
            
            logging.debug(f"Testing connectivity to share host: {hostname}")
            
            # First try DNS lookup (faster and more reliable)
            try:
                process = await asyncio.create_subprocess_exec(
                    "nslookup", hostname,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5.0)
                
                if process.returncode == 0:
                    # DNS lookup succeeded, host is reachable
                    logging.debug(f"DNS lookup successful for {hostname}")
                    return True
                else:
                    logging.debug(f"DNS lookup failed for {hostname}, trying ping...")
            except Exception as e:
                logging.debug(f"DNS lookup error for {hostname}: {e}, trying ping...")
            
            # Fallback to ping if DNS lookup fails
            # macOS ping syntax: -c count -W timeout_in_milliseconds
            process = await asyncio.create_subprocess_exec(
                "ping", "-c", "1", "-W", "3000", hostname,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=8.0)
            
            if process.returncode == 0:
                logging.debug(f"Successfully pinged share host: {hostname}")
                return True
            else:
                error_msg = stderr.decode() if stderr else "No response"
                logging.warning(f"Cannot reach share host {hostname}: {error_msg}")
                return False
                
        except asyncio.TimeoutError:
            logging.warning("Timeout while testing connectivity to share host")
            return False
        except Exception as e:
            logging.error(f"Error testing share host connectivity: {e}")
            return False


class MacOSMountCleaner:
    """Cleans up invalid mount states and ghost mounts."""
    
    def __init__(self, mount_validator: MacOSMountValidator):
        self._validator = mount_validator
    
    async def cleanup_invalid_mount_point(self, mount_path: str) -> bool:
        """
        Clean up invalid state at mount point.
        
        Removes local folders that shouldn't exist at mount points.
        WARNING: Only call this if you're sure it's not supposed to be a local folder!
        """
        try:
            # First check if it's a real network mount - don't touch those!
            if await self._validator.is_real_network_mount(mount_path):
                logging.info(f"Mount point is valid network mount, not cleaning: {mount_path}")
                return True
            
            # Check if it's a local folder that shouldn't be there
            if await self._validator.is_local_folder_at_mount_point(mount_path):
                logging.warning(f"Found invalid local folder at mount point: {mount_path}")
                
                path_obj = Path(mount_path)
                
                # Safety check - only remove if it's in /Volumes/ 
                if not str(path_obj).startswith('/Volumes/'):
                    logging.error(f"Refusing to remove folder outside /Volumes/: {mount_path}")
                    return False
                
                # Try to remove the invalid local folder
                try:
                    await asyncio.to_thread(path_obj.rmdir)
                    logging.info(f"Removed invalid local folder: {mount_path}")
                    return True
                except OSError as e:
                    # Folder might not be empty
                    logging.error(f"Could not remove invalid local folder {mount_path}: {e}")
                    return False
            
            # Path doesn't exist or is not problematic
            return True
            
        except Exception as e:
            logging.error(f"Error cleaning up mount point {mount_path}: {e}")
            return False
    
    async def cleanup_ghost_mounts(self, base_mount_path: str) -> List[str]:
        """
        Clean up ghost mounts like /Volumes/SK6402_1.
        
        Returns list of cleaned up ghost mount paths.
        """
        cleaned_paths = []
        
        try:
            ghost_mounts = await self._validator.find_ghost_mounts(base_mount_path)
            
            for ghost_path in ghost_mounts:
                logging.warning(f"Found ghost mount: {ghost_path}")
                
                # Check if it's actually mounted
                if await self._validator.is_real_network_mount(ghost_path):
                    logging.info(f"Ghost mount is actually a valid network mount, unmounting: {ghost_path}")
                    if await self._unmount_path(ghost_path):
                        cleaned_paths.append(ghost_path)
                else:
                    # It's just a local folder, remove it
                    logging.info(f"Ghost mount is local folder, removing: {ghost_path}")
                    try:
                        path_obj = Path(ghost_path)
                        await asyncio.to_thread(path_obj.rmdir)
                        cleaned_paths.append(ghost_path)
                        logging.info(f"Removed ghost mount folder: {ghost_path}")
                    except OSError as e:
                        logging.error(f"Could not remove ghost mount folder {ghost_path}: {e}")
            
            return cleaned_paths
            
        except Exception as e:
            logging.error(f"Error cleaning up ghost mounts for {base_mount_path}: {e}")
            return []
    
    async def _unmount_path(self, mount_path: str) -> bool:
        """Unmount a path using diskutil."""
        try:
            process = await asyncio.create_subprocess_exec(
                "diskutil", "unmount", mount_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10.0)
            
            if process.returncode == 0:
                logging.info(f"Successfully unmounted: {mount_path}")
                return True
            else:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logging.error(f"Failed to unmount {mount_path}: {error_msg}")
                return False
                
        except Exception as e:
            logging.error(f"Error unmounting {mount_path}: {e}")
            return False