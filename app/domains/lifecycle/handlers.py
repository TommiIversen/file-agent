"""
Lifecycle Domain Handlers
Handlers responsible for managing file lifecycle operations.
"""
import logging
from datetime import datetime, timedelta
from typing import Set

from app.core.file_repository import FileRepository
from app.models import FileStatus
from .commands import PruneOldFilesCommand


class PruneOldFilesCommandHandler:
    """
    Handler responsible solely for pruning old files from the repository.
    
    This class adheres to SRP by focusing only on the cleanup logic
    for terminal files that have exceeded the retention period.
    """

    def __init__(self, file_repository: FileRepository):
        self._repository = file_repository

        # DEFINE TERMINAL STATES
        # We NEVER touch active files (DISCOVERED, READY, IN_QUEUE, COPYING etc.)
        self._TERMINAL_STATES: Set[FileStatus] = {
            FileStatus.COMPLETED,
            FileStatus.COMPLETED_DELETE_FAILED,
            FileStatus.FAILED,
            FileStatus.REMOVED,
            FileStatus.SPACE_ERROR,
        }

    async def handle(self, command: PruneOldFilesCommand) -> None:
        """
        Execute the repository cleanup operation.
        
        This method is responsible for coordinating the cleanup by calling
        the specialized repository method. The actual logic is delegated
        to the repository layer for better separation of concerns.
        """
        logging.info(f"Starting cleanup of files older than {command.hours_to_keep} hours...")

        cutoff_date = datetime.now() - timedelta(hours=command.hours_to_keep)

        # Call the new, efficient repository method
        pruned_count = await self._repository.prune_terminal_files(
            terminal_states=self._TERMINAL_STATES,
            cutoff_date=cutoff_date
        )

        if pruned_count == 0:
            logging.info("Cleanup completed. No old files found.")
        else:
            logging.info(f"Cleanup completed. {pruned_count} old, terminal files were deleted.")