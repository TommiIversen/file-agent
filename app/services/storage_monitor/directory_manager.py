import asyncio
import logging
from pathlib import Path


class DirectoryManager:

    def __init__(self):
        pass

    async def ensure_directory_exists(self, path: str, storage_type: str) -> bool:
        """
        Ensure directory exists with async timeout for network paths.
        Returns False for network errors without hanging.
        """
        try:
            path_obj = Path(path)

            # Quick check if directory already exists
            if path_obj.exists() and path_obj.is_dir():
                return True

            logging.info(f"Creating missing {storage_type} directory: {path}")
            
            # For network paths, use asyncio timeout to prevent hanging
            try:
                await asyncio.wait_for(
                    self._create_directory_async(path_obj), 
                    timeout=2.0  # Reduce to 2 seconds for faster startup
                )
            except asyncio.TimeoutError:
                logging.warning(f"Directory creation timeout (2s) for {storage_type} at {path} - network offline")
                return False

            if path_obj.exists() and path_obj.is_dir():
                logging.info(f"Successfully created {storage_type} directory: {path}")
                return True
            else:
                logging.error(
                    f"Directory creation appeared successful but verification failed: {path}"
                )
                return False

        except Exception as e:
            logging.error(f"Failed to create {storage_type} directory {path}: {e}")
            return False

    async def _create_directory_async(self, path_obj: Path) -> None:
        """Create directory in executor to avoid blocking event loop"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, 
            lambda: path_obj.mkdir(parents=True, exist_ok=True)
        )
