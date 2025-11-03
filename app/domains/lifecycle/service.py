"""
Lifecycle Domain Service
Background service responsible for periodic lifecycle management tasks.
"""
import asyncio
import logging
from typing import Optional

from app.config import Settings
from app.core.cqrs.command_bus import CommandBus
from .commands import PruneOldFilesCommand


class LifecycleService:
    """
    Service responsible solely for running periodic background tasks
    for file lifecycle management.
    
    This class adheres to SRP by focusing only on the scheduling and
    execution of lifecycle maintenance operations.
    """

    def __init__(self, command_bus: CommandBus, settings: Settings):
        self._command_bus = command_bus
        self._settings = settings
        self._running = False
        self._task: Optional[asyncio.Task] = None
        # Run every 6 hours (can be adjusted)
        self._prune_interval_seconds = 6 * 3600 

    async def start_pruning_loop(self) -> None:
        """
        Start the infinite loop that periodically cleans up old files.
        
        This method is responsible for managing the background cleanup
        schedule and error handling.
        """
        if self._running:
            logging.warning("LifecycleService is already running")
            return

        self._running = True
        logging.info(f"LifecycleService started. Will cleanup every {self._prune_interval_seconds / 3600} hours.")

        while self._running:
            try:
                await asyncio.sleep(self._prune_interval_seconds)

                if not self._running:  # Check if we were stopped during sleep
                    break

                logging.info("LifecycleService: Triggering PruneOldFilesCommand...")
                command = PruneOldFilesCommand(
                    hours_to_keep=self._settings.keep_files_hours
                )
                await self._command_bus.execute(command)

            except asyncio.CancelledError:
                self._running = False
                logging.info("LifecycleService stopped.")
                break
            except Exception as e:
                logging.error(f"Error in LifecycleService: {e}")
                # Wait a minute before retrying on error
                await asyncio.sleep(60)

    def stop_pruning_loop(self) -> None:
        """
        Stop the cleanup loop.
        
        This method is responsible for gracefully shutting down
        the background service.
        """
        logging.info("LifecycleService stop requested")
        self._running = False
        if self._task:
            self._task.cancel()

    def is_running(self) -> bool:
        """Check if the service is currently running."""
        return self._running