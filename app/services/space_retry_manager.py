import asyncio
import logging

from app.models import TrackedFile
from ..config import Settings
from ..models import FileStatus, SpaceCheckResult
from ..services.state_manager import StateManager


class SpaceRetryManager:
    def __init__(self, settings: Settings, state_manager: StateManager):
        self._settings = settings
        self._state_manager = state_manager

        logging.debug("SpaceRetryManager initialized - retry tracking delegated to StateManager")

    async def schedule_space_retry(
            self, tracked_file: TrackedFile, space_check: SpaceCheckResult
    ) -> None:
        # Increment retry count using StateManager
        retry_count = await self._state_manager.increment_retry_count(tracked_file.id)
        
        if self._should_give_up_retry(retry_count):
            await self._mark_as_permanent_space_error(tracked_file, space_check)
            return

        if space_check.is_temporary_shortage():
            await self._schedule_short_retry(tracked_file, space_check)
        else:
            await self._schedule_long_retry(tracked_file, space_check)

    async def _schedule_short_retry(
            self, tracked_file: TrackedFile, space_check: SpaceCheckResult
    ) -> None:
        delay_seconds = self._settings.space_retry_delay_seconds // 2

        # Update file status to WAITING_FOR_SPACE
        await self._state_manager.update_file_status_by_id(
            file_id=tracked_file.id,
            status=FileStatus.WAITING_FOR_SPACE,
            error_message=f"Temporary space shortage: {space_check.reason}. Retrying in {delay_seconds // 60} minutes.",
        )
        
        # Schedule retry using StateManager
        success = await self._state_manager.schedule_retry(
            tracked_file.id, 
            delay_seconds, 
            f"Temporary space shortage: {space_check.reason}",
            "space"
        )
        
        if success:
            logging.debug(f"SPACE RETRY SHORT: {tracked_file.file_path} [UUID: {tracked_file.id[:8]}...]")
        else:
            logging.warning(f"Failed to schedule short retry for {tracked_file.file_path}")

    async def _schedule_long_retry(
            self, tracked_file: TrackedFile, space_check: SpaceCheckResult
    ) -> None:
        delay_seconds = self._settings.space_retry_delay_seconds

        # Update file status to WAITING_FOR_SPACE  
        await self._state_manager.update_file_status_by_id(
            file_id=tracked_file.id,
            status=FileStatus.WAITING_FOR_SPACE,
            error_message=f"Insufficient space: {space_check.reason}. Retrying in {delay_seconds // 60} minutes.",
        )
        
        # Schedule retry using StateManager
        success = await self._state_manager.schedule_retry(
            tracked_file.id,
            delay_seconds,
            f"Insufficient space: {space_check.reason}",
            "space"
        )
        
        if success:
            logging.debug(f"SPACE RETRY LONG: {tracked_file.file_path} [UUID: {tracked_file.id[:8]}...]")
        else:
            logging.warning(f"Failed to schedule long retry for {tracked_file.file_path}")



    async def _mark_as_permanent_space_error(
            self, tracked_file: TrackedFile, space_check: SpaceCheckResult
    ) -> None:
        if tracked_file:
            await self._state_manager.update_file_status_by_id(
                file_id=tracked_file.id,
                status=FileStatus.SPACE_ERROR,
                error_message=f"Permanent space issue after {self._settings.max_space_retries} retries: {space_check.reason}",
            )
            logging.debug(
                f"PERMANENT SPACE ERROR: {tracked_file.file_path} [UUID: {tracked_file.id[:8]}...]"
            )
        else:
            logging.warning(
                f"Cannot mark space error - file not tracked: {tracked_file.file_path}"
            )

        logging.warning(
            f"File {tracked_file.file_path} marked as permanent space error after max retries",
            extra={
                "operation": "permanent_space_error",
                "file_path": tracked_file.file_path,
                "max_retries": self._settings.max_space_retries,
                "shortage_gb": space_check.get_shortage_gb(),
            },
        )



    def _should_give_up_retry(self, current_retry_count: int) -> bool:
        return current_retry_count >= self._settings.max_space_retries

    async def cancel_all_retries(self) -> None:
        """Cancel all pending space retries."""
        logging.info("Cancelling all space retries")
        cancelled_count = await self._state_manager.cancel_all_retries()
        logging.info(f"Cancelled {cancelled_count} space retry operations")



