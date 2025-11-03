"""
File Repository - A pure data access layer for TrackedFile objects.
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Set

from app.models import TrackedFile, FileStatus


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

    async def prune_terminal_files(
        self, 
        terminal_states: Set[FileStatus], 
        cutoff_date: datetime
    ) -> int:
        """
        Find and delete all files that are in a terminal state
        AND older than cutoff_date.

        Returns the number of files that were deleted.

        IMPORTANT: This in-memory implementation iterates, but 
        the SQL version will make a single, efficient DELETE call.
        """
        files_to_prune = []
        pruned_count = 0

        # Take the lock once for the entire operation
        async with self._lock:
            # Find candidates (iterate over a copy to avoid 'dict changed size')
            all_files = list(self._files_by_id.values()) 

            for file in all_files:
                if file.status in terminal_states:
                    # Find the most recent relevant timestamp
                    last_activity_time = (
                        file.completed_at or 
                        file.failed_at or 
                        file.space_error_at or 
                        file.discovered_at  # Fallback
                    )

                    if last_activity_time and last_activity_time < cutoff_date:
                        files_to_prune.append(file.id)

            # Perform deletion
            for file_id in files_to_prune:
                if file_id in self._files_by_id:
                    del self._files_by_id[file_id]
                    pruned_count += 1

        return pruned_count
