"""
File Repository - A pure data access layer for TrackedFile objects.
"""

import asyncio
import logging
from typing import Dict, List, Optional

from app.models import TrackedFile


class FileRepository:
    """
    Provides a thread-safe, in-memory repository for TrackedFile objects.
    This class is responsible for the direct storage and retrieval of file data,
    acting as a thin data access layer.
    """

    def __init__(self):
        self._files_by_id: Dict[str, TrackedFile] = {}
        self._lock = asyncio.Lock()
        logging.info("FileRepository initialized")

    async def get_by_id(self, file_id: str) -> Optional[TrackedFile]:
        """Get a single tracked file by its unique ID."""
        async with self._lock:
            return self._files_by_id.get(file_id)

    async def get_all(self) -> List[TrackedFile]:
        """Get a list of all tracked files."""
        async with self._lock:
            return list(self._files_by_id.values())

    async def add(self, tracked_file: TrackedFile) -> None:
        """Add a new tracked file to the repository."""
        async with self._lock:
            if tracked_file.id in self._files_by_id:
                logging.error(
                    f"File with ID {tracked_file.id} already exists in repository. Use update() to modify."
                )
                return
            self._files_by_id[tracked_file.id] = tracked_file

    async def update(self, tracked_file: TrackedFile) -> None:
        """Update an existing tracked file in the repository."""
        async with self._lock:
            if tracked_file.id not in self._files_by_id:
                logging.warning(
                    f"File with ID {tracked_file.id} does not exist in repository. Cannot update."
                )
            self._files_by_id[tracked_file.id] = tracked_file

    async def remove(self, file_id: str) -> bool:
        """Remove a tracked file from the repository by its ID."""
        async with self._lock:
            if file_id in self._files_by_id:
                del self._files_by_id[file_id]
                return True
            return False

    async def count(self) -> int:
        """Return the total number of files in the repository."""
        async with self._lock:
            return len(self._files_by_id)
