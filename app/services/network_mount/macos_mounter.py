"""macOS Network Mounter - SRP compliant."""

import asyncio
import logging
from pathlib import Path
from typing import Tuple

from .base_mounter import BaseMounter


class MacOSMounter(BaseMounter):
    """macOS-specific network mount implementation."""

    def __init__(self):
        super().__init__()

    async def attempt_mount(self, share_url: str) -> bool:
        """Attempt to mount network share using macOS osascript."""
        try:
            logging.info(f"Attempting macOS mount: {share_url}")

            cmd = ["osascript", "-e", f'mount volume "{share_url}"']

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            _, stderr = await process.communicate()

            if process.returncode == 0:
                logging.info(f"Successfully mounted {share_url}")
                return True
            else:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logging.error(f"Mount failed for {share_url}: {error_msg}")
                return False

        except Exception as e:
            logging.error(f"Exception during macOS mount attempt: {e}")
            return False

    async def verify_mount_accessible(self, local_path: str) -> Tuple[bool, bool]:
        """Verify if mount point is accessible and writable on macOS."""
        try:
            path_obj = Path(local_path)

            if not path_obj.exists():
                logging.debug(f"Mount point does not exist: {local_path}")
                return False, False

            if not path_obj.is_dir():
                logging.debug(f"Mount point is not a directory: {local_path}")
                return True, False

            try:
                process = await asyncio.create_subprocess_exec(
                    "ls",
                    local_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                _, stderr = await process.communicate()

                if process.returncode == 0:
                    logging.debug(f"Mount point accessible: {local_path}")
                    return True, True
                else:
                    error_msg = stderr.decode() if stderr else "Unknown error"
                    logging.debug(
                        f"Mount point not accessible: {local_path} - {error_msg}"
                    )
                    return True, False

            except Exception as e:
                logging.debug(f"Error testing mount accessibility: {e}")
                return True, False

        except Exception as e:
            logging.error(f"Exception during mount verification: {e}")
            return False, False

    def get_platform_name(self) -> str:
        """Get platform name for logging."""
        return "macOS"

    def get_mount_point_from_url(self, share_url: str) -> str:
        """Derive expected mount point from share URL."""
        try:
            if "/" in share_url:
                share_name = share_url.split("/")[-1]
            else:
                share_name = share_url

            mount_point = f"/Volumes/{share_name}"
            logging.debug(f"Derived mount point: {mount_point} from URL: {share_url}")
            return mount_point

        except Exception as e:
            logging.error(f"Error deriving mount point from URL {share_url}: {e}")
            return "/Volumes/NetworkShare"
