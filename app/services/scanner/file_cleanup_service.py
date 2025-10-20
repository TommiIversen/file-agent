import logging
from typing import Set

from .domain_objects import FilePath, ScanConfiguration


class FileCleanupService:

    def __init__(self, config: ScanConfiguration, state_manager):
        self.config = config
        self.state_manager = state_manager

    async def cleanup_missing_files(self, current_files: Set[FilePath]) -> int:
        try:
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

    async def cleanup_old_files(self) -> int:
        try:
            removed_count = await self.state_manager.cleanup_old_files(
                max_age_hours=self.config.keep_files_hours,
            )

            if removed_count > 0:
                logging.info(
                    f"Cleanup: Removed {removed_count} old files from memory "
                    f"(older than {self.config.keep_files_hours} hours)"
                )

            return removed_count

        except Exception as e:
            logging.error(f"Error cleaning up old files: {e}")
            return 0
