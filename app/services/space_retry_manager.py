import asyncio
from typing import Dict
from datetime import datetime, timedelta
import logging
from app.models import TrackedFile

from ..config import Settings

from ..models import FileStatus, SpaceCheckResult
from ..services.state_manager import StateManager


class SpaceRetryManager:
    def __init__(self, settings: Settings, state_manager: StateManager):
        self._settings = settings
        self._state_manager = state_manager

        self._retry_tracking: Dict[str, RetryInfo] = {}
        self._retry_tasks: Dict[str, asyncio.Task] = {}

        logging.debug("SpaceRetryManager initialized")

    async def schedule_space_retry(
        self, tracked_file: TrackedFile, space_check: SpaceCheckResult
    ) -> None:
        if self._should_give_up_retry(tracked_file.retry_count):
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

        if tracked_file:
            await self._state_manager.update_file_status_by_id(
                file_id=tracked_file.id,
                status=FileStatus.WAITING_FOR_SPACE,
                error_message=f"Temporary space shortage: {space_check.reason}. Retrying in {delay_seconds // 60} minutes.",
            )
            logging.debug(
                f"SPACE RETRY SHORT: {tracked_file.file_path} [UUID: {tracked_file.id}"
            )
        else:
            logging.warning(
                f"Cannot schedule retry - file not tracked: {tracked_file.file_path}"
            )

        await self._schedule_retry_task(
            tracked_file, delay_seconds, "temporary shortage"
        )

    async def _schedule_long_retry(
        self, tracked_file: TrackedFile, space_check: SpaceCheckResult
    ) -> None:
        delay_seconds = self._settings.space_retry_delay_seconds

        if tracked_file:
            await self._state_manager.update_file_status_by_id(
                file_id=tracked_file.id,
                status=FileStatus.WAITING_FOR_SPACE,
                error_message=f"Insufficient space: {space_check.reason}. Retrying in {delay_seconds // 60} minutes.",
            )
            logging.debug(
                f"SPACE RETRY LONG: {tracked_file.file_path} [UUID: {tracked_file.id[:8]}...]"
            )
        else:
            logging.warning(
                f"Cannot schedule retry - file not tracked: {tracked_file.file_path}"
            )

        await self._schedule_retry_task(tracked_file, delay_seconds, "space shortage")

    async def _schedule_retry_task(
        self, tracked_file: TrackedFile, delay_seconds: int, reason: str
    ) -> None:
        await self._cancel_existing_retry_by_id(tracked_file.id)

        retry_info = RetryInfo(
            file_path=tracked_file.file_path,
            scheduled_at=datetime.now(),
            retry_at=datetime.now() + timedelta(seconds=delay_seconds),
            reason=reason,
        )
        self._retry_tracking[tracked_file.id] = retry_info

        retry_task = asyncio.create_task(
            self._execute_delayed_retry(tracked_file, delay_seconds)
        )
        self._retry_tasks[tracked_file.id] = retry_task

        logging.info(
            f"Scheduled space retry for {tracked_file.file_path} in {delay_seconds}s due to {reason}",
            extra={
                "operation": "space_retry_scheduled",
                "file_path": tracked_file.file_path,
                "delay_seconds": delay_seconds,
                "reason": reason,
            },
        )

    async def _execute_delayed_retry(
        self, tracked_file: TrackedFile, delay_seconds: int
    ) -> None:
        try:
            await asyncio.sleep(delay_seconds)

            if not tracked_file or tracked_file.status != FileStatus.WAITING_FOR_SPACE:
                logging.debug(
                    f"File {tracked_file.file_path} no longer needs space retry"
                )
                return

            await self._state_manager.update_file_status_by_id(
                file_id=tracked_file.id,
                status=FileStatus.READY,
                error_message=None,
            )

            logging.info(
                f"Space retry executed for {tracked_file.file_path} - reset to READY",
                extra={
                    "operation": "space_retry_executed",
                    "file_path": tracked_file.file_path,
                },
            )

        except asyncio.CancelledError:
            logging.debug(f"Space retry cancelled for {tracked_file.file_path}")
        except Exception as e:
            logging.error(f"Error in space retry for {tracked_file.file_path}: {e}")
        finally:
            self._retry_tracking.pop(tracked_file.id, None)
            self._retry_tasks.pop(tracked_file.id, None)

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

    async def _cancel_existing_retry_by_id(self, tracked_file_id: str) -> None:
        if tracked_file_id in self._retry_tasks:
            task = self._retry_tasks.pop(tracked_file_id)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._retry_tracking.pop(tracked_file_id, None)

    def _should_give_up_retry(self, current_retry_count: int) -> bool:
        return current_retry_count >= self._settings.max_space_retries

    async def cancel_all_retries(self) -> None:
        logging.info("Cancelling all space retries")

        for file_path in list(self._retry_tasks.keys()):
            await self._cancel_existing_retry_by_id(file_path)


class RetryInfo:
    def __init__(
        self, file_path: str, scheduled_at: datetime, retry_at: datetime, reason: str
    ):
        self.file_path = file_path
        self.scheduled_at = scheduled_at
        self.retry_at = retry_at
        self.reason = reason
