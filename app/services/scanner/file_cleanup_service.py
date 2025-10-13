# This class is responsible solely for cleanup operations, adhering to SRP.
import logging
from typing import Set
from .domain_objects import FilePath, ScanConfiguration


class FileCleanupService:
    """
    Focused service responsible only for cleanup operations.

    Single Responsibility: File cleanup and maintenance operations
    """

    def __init__(self, config: ScanConfiguration, state_manager):
        self.config = config
        self.state_manager = state_manager

    async def cleanup_missing_files(self, current_files: Set[FilePath]) -> int:
        """
        Remove files from StateManager that no longer exist on disk.

        Args:
            current_files: Set of FilePath objects that exist on disk

        Returns:
            Number of files removed
        """
        try:
            # Convert FilePath objects to strings for state manager compatibility
            current_file_paths = {fp.path for fp in current_files}

            removed_count = await self.state_manager.cleanup_missing_files(
                current_file_paths
            )

            if removed_count > 0:
                logging.info(
                    f"Cleanup: Removed {removed_count} files that no longer exist"
                )

            return removed_count

        except Exception as e:
            logging.error(f"Error cleaning up missing files: {e}")
            return 0

    async def cleanup_old_completed_files(self) -> int:
        """
        Remove old completed files from memory to keep memory usage low.

        Returns:
            Number of files removed
        """
        try:
            removed_count = await self.state_manager.cleanup_old_completed_files(
                max_age_hours=self.config.keep_completed_files_hours,
                max_count=self.config.max_completed_files_in_memory,
            )

            if removed_count > 0:
                logging.info(
                    f"Cleanup: Removed {removed_count} old completed files from memory"
                )

            return removed_count

        except Exception as e:
            logging.error(f"Error cleaning up old completed files: {e}")
            return 0
