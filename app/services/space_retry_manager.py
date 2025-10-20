"""
Space Retry Manager for File Transfer Agent.

Handles retry logic for files waiting for disk space.
Follows Single Responsibility Principle - only manages space retries.
"""

import asyncio
from typing import Dict
from datetime import datetime, timedelta
import logging
from ..config import Settings

from ..models import FileStatus, SpaceCheckResult
from ..services.state_manager import StateManager


class SpaceRetryManager:
    """
    Manages retry logic for files waiting for disk space.

    Responsibilities:
    - Schedule retries for files waiting for space
    - Track retry counts and timeouts
    - Determine when to give up (permanent space error)
    - Clean architecture - separate from copying logic

    Design Principles:
    - Single Responsibility: Only handles retry scheduling
    - No file operations: Delegates back to FileCopyService
    - State tracking: Maintains retry metadata
    """

    def __init__(self, settings: Settings, state_manager: StateManager):
        """
        Initialize SpaceRetryManager.

        Args:
            settings: Application configuration
            state_manager: Central state manager for file tracking
        """
        self._settings = settings
        self._state_manager = state_manager

        # Track files waiting for space retry
        self._retry_tracking: Dict[str, RetryInfo] = {}
        self._retry_tasks: Dict[str, asyncio.Task] = {}

        logging.debug("SpaceRetryManager initialized")

    async def schedule_space_retry(
        self, file_path: str, space_check: SpaceCheckResult
    ) -> None:
        """
        Schedule a retry for a file that couldn't be copied due to space.

        Args:
            file_path: Path to file that needs retry
            space_check: Result of space check that failed
        """
        tracked_file = await self._state_manager.get_file_by_path(file_path)
        if not tracked_file:
            logging.warning(f"Cannot schedule retry for unknown file: {file_path}")
            return

        # Check if we should retry or give up
        if self._should_give_up_retry(tracked_file.retry_count):
            await self._mark_as_permanent_space_error(file_path, space_check)
            return

        # Determine retry strategy based on shortage type
        if space_check.is_temporary_shortage():
            await self._schedule_temporary_retry(file_path, space_check)
        else:
            await self._schedule_long_retry(file_path, space_check)

    async def _schedule_short_retry(
        self, file_path: str, space_check: SpaceCheckResult
    ) -> None:
        """Schedule retry for temporary space shortage (shorter delay) - UUID precision"""
        # Shorter delay for temporary shortages (space might free up soon)
        delay_seconds = (
            self._settings.space_retry_delay_seconds // 2
        )  # Half normal delay

        # Get tracked file for UUID-based update
        tracked_file = await self._state_manager.get_file_by_path(file_path)
        if tracked_file:
            await self._state_manager.update_file_status_by_id(
                file_id=tracked_file.id,  # Precise UUID reference
                status=FileStatus.WAITING_FOR_SPACE,
                error_message=f"Temporary space shortage: {space_check.reason}. Retrying in {delay_seconds // 60} minutes.",
            )
            logging.debug(f"SPACE RETRY SHORT: {file_path} [UUID: {tracked_file.id[:8]}...]")
        else:
            logging.warning(f"Cannot schedule retry - file not tracked: {file_path}")

        await self._schedule_retry_task(file_path, delay_seconds, "temporary shortage")

    async def _schedule_long_retry(
        self, file_path: str, space_check: SpaceCheckResult
    ) -> None:
        """Schedule retry for significant space shortage (longer delay) - UUID precision"""
        delay_seconds = self._settings.space_retry_delay_seconds

        # Get tracked file for UUID-based update  
        tracked_file = await self._state_manager.get_file_by_path(file_path)
        if tracked_file:
            await self._state_manager.update_file_status_by_id(
                file_id=tracked_file.id,  # Precise UUID reference
                status=FileStatus.WAITING_FOR_SPACE,
                error_message=f"Insufficient space: {space_check.reason}. Retrying in {delay_seconds // 60} minutes.",
            )
            logging.debug(f"SPACE RETRY LONG: {file_path} [UUID: {tracked_file.id[:8]}...]")
        else:
            logging.warning(f"Cannot schedule retry - file not tracked: {file_path}")

        await self._schedule_retry_task(file_path, delay_seconds, "space shortage")

    async def _schedule_retry_task(
        self, file_path: str, delay_seconds: int, reason: str
    ) -> None:
        """Create async task to retry file after delay"""
        # Cancel existing retry task if any
        await self._cancel_existing_retry(file_path)

        # Track retry info
        retry_info = RetryInfo(
            file_path=file_path,
            scheduled_at=datetime.now(),
            retry_at=datetime.now() + timedelta(seconds=delay_seconds),
            reason=reason,
        )
        self._retry_tracking[file_path] = retry_info

        # Create retry task
        retry_task = asyncio.create_task(
            self._execute_delayed_retry(file_path, delay_seconds)
        )
        self._retry_tasks[file_path] = retry_task

        logging.info(
            f"Scheduled space retry for {file_path} in {delay_seconds}s due to {reason}",
            extra={
                "operation": "space_retry_scheduled",
                "file_path": file_path,
                "delay_seconds": delay_seconds,
                "reason": reason,
            },
        )

    async def _execute_delayed_retry(self, file_path: str, delay_seconds: int) -> None:
        """Execute the delayed retry after waiting"""
        try:
            await asyncio.sleep(delay_seconds)

            # Check if file still exists and needs retry
            tracked_file = await self._state_manager.get_file_by_path(file_path)
            if not tracked_file or tracked_file.status != FileStatus.WAITING_FOR_SPACE:
                logging.debug(f"File {file_path} no longer needs space retry")
                return

            # Reset to READY status so FileCopyService will pick it up again - UUID precision
            await self._state_manager.update_file_status_by_id(
                file_id=tracked_file.id,  # Precise UUID reference
                status=FileStatus.READY, 
                error_message=None
            )

            logging.info(
                f"Space retry executed for {file_path} - reset to READY",
                extra={"operation": "space_retry_executed", "file_path": file_path},
            )

        except asyncio.CancelledError:
            logging.debug(f"Space retry cancelled for {file_path}")
        except Exception as e:
            logging.error(f"Error in space retry for {file_path}: {e}")
        finally:
            # Cleanup tracking
            self._retry_tracking.pop(file_path, None)
            self._retry_tasks.pop(file_path, None)

    async def _mark_as_permanent_space_error(
        self, file_path: str, space_check: SpaceCheckResult
    ) -> None:
        """Mark file as permanent space error after max retries - UUID precision"""
        # Get tracked file for UUID-based update
        tracked_file = await self._state_manager.get_file_by_path(file_path)
        if tracked_file:
            await self._state_manager.update_file_status_by_id(
                file_id=tracked_file.id,  # Precise UUID reference
                status=FileStatus.SPACE_ERROR,
                error_message=f"Permanent space issue after {self._settings.max_space_retries} retries: {space_check.reason}",
            )
            logging.debug(f"PERMANENT SPACE ERROR: {file_path} [UUID: {tracked_file.id[:8]}...]")
        else:
            logging.warning(f"Cannot mark space error - file not tracked: {file_path}")

        logging.warning(
            f"File {file_path} marked as permanent space error after max retries",
            extra={
                "operation": "permanent_space_error",
                "file_path": file_path,
                "max_retries": self._settings.max_space_retries,
                "shortage_gb": space_check.get_shortage_gb(),
            },
        )

    async def _cancel_existing_retry(self, file_path: str) -> None:
        """Cancel existing retry task for file"""
        if file_path in self._retry_tasks:
            task = self._retry_tasks.pop(file_path)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._retry_tracking.pop(file_path, None)

    def _should_give_up_retry(self, current_retry_count: int) -> bool:
        """Determine if we should give up retrying due to max attempts"""
        return current_retry_count >= self._settings.max_space_retries

    async def cancel_all_retries(self) -> None:
        """Cancel all pending space retries (for shutdown)"""
        logging.info("Cancelling all space retries")

        for file_path in list(self._retry_tasks.keys()):
            await self._cancel_existing_retry(file_path)

    def get_retry_status(self) -> Dict[str, dict]:
        """Get status of all pending space retries"""
        status = {}
        for file_path, retry_info in self._retry_tracking.items():
            status[file_path] = {
                "scheduled_at": retry_info.scheduled_at,
                "retry_at": retry_info.retry_at,
                "reason": retry_info.reason,
                "seconds_remaining": max(
                    0, int((retry_info.retry_at - datetime.now()).total_seconds())
                ),
            }
        return status


class RetryInfo:
    """Information about a scheduled space retry"""

    def __init__(
        self, file_path: str, scheduled_at: datetime, retry_at: datetime, reason: str
    ):
        self.file_path = file_path
        self.scheduled_at = scheduled_at
        self.retry_at = retry_at
        self.reason = reason
