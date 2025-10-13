"""Windows Network Mounter - SRP compliant."""

import asyncio
import logging
from pathlib import Path
from typing import Tuple, Optional

from .base_mounter import BaseMounter



class WindowsMounter(BaseMounter):
    """Windows-specific network mount implementation. SRP: Windows mount operations ONLY."""
    
    def __init__(self, drive_letter: Optional[str] = None):
        super().__init__()
        self._drive_letter = drive_letter
        
    
    async def attempt_mount(self, share_url: str) -> bool:
        """Mount network share using Windows net use command."""
        try:
            # Convert smb:// URL to UNC path format
            unc_path = self._convert_url_to_unc(share_url)
            logging.info(f"Attempting Windows mount: {unc_path}")
            
            if self._drive_letter:
                # Mount to specific drive letter
                cmd = ['net', 'use', f'{self._drive_letter}:', unc_path, '/persistent:yes']
                logging.debug(f"Using drive letter {self._drive_letter}: for mount")
            else:
                # Mount without drive letter (UNC access)
                cmd = ['net', 'use', unc_path]
                logging.debug("Using UNC path access (no drive letter)")
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                mount_point = f"{self._drive_letter}:\\" if self._drive_letter else unc_path
                logging.info(f"Successfully mounted {unc_path} as {mount_point}")
                return True
            else:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logging.error(f"Mount failed for {unc_path}: {error_msg}")
                return False
                
        except Exception as e:
            logging.error(f"Exception during Windows mount attempt: {e}")
            return False
    
    async def verify_mount_accessible(self, local_path: str) -> Tuple[bool, bool]:
        """Verify if mount point is accessible on Windows."""
        try:
            path_obj = Path(local_path)
            
            # Check if mount point exists
            if not path_obj.exists():
                logging.debug(f"Mount point does not exist: {local_path}")
                return False, False
            
            # Check if it's a directory
            if not path_obj.is_dir():
                logging.debug(f"Mount point is not a directory: {local_path}")
                return True, False
            
            # Test accessibility by trying to list directory
            try:
                # Use dir command for Windows
                process = await asyncio.create_subprocess_exec(
                    'dir', local_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    shell=True
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0:
                    logging.debug(f"Mount point accessible: {local_path}")
                    return True, True
                else:
                    error_msg = stderr.decode() if stderr else "Unknown error"
                    logging.debug(f"Mount point not accessible: {local_path} - {error_msg}")
                    return True, False
                    
            except Exception as e:
                logging.debug(f"Error testing mount accessibility: {e}")
                return True, False
            
        except Exception as e:
            logging.error(f"Exception during mount verification: {e}")
            return False, False
    
    def get_platform_name(self) -> str:
        """Get platform name for logging."""
        return "Windows"
    
    def _convert_url_to_unc(self, share_url: str) -> str:
        """Convert SMB URL to Windows UNC path format."""
        try:
            # Remove smb:// prefix
            if share_url.startswith('smb://'):
                path_part = share_url[6:]  # Remove 'smb://'
            else:
                path_part = share_url
            
            # Convert forward slashes to backslashes and add UNC prefix
            unc_path = '\\\\' + path_part.replace('/', '\\')
            
            logging.debug(f"Converted {share_url} to UNC path: {unc_path}")
            return unc_path
            
        except Exception as e:
            logging.error(f"Error converting URL to UNC path: {e}")
            # Return as-is if conversion fails
            return share_url
    
    def get_mount_point_from_url(self, share_url: str) -> str:
        """Get expected mount point from share URL."""
        if self._drive_letter:
            return f"{self._drive_letter}:\\"
        else:
            return self._convert_url_to_unc(share_url)
