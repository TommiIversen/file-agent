
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

from app.core.file_repository import FileRepository
from app.core.events.event_bus import DomainEventBus
from app.core.events.file_events import FileStatusChangedEvent
from app.models import TrackedFile, FileStatus, RetryInfo, SpaceCheckResult
from ..config import Settings



class SpaceRetryManager:
    def __init__(
        self,
        settings: Settings,
        file_repository: FileRepository,
        event_bus: DomainEventBus,
    ):
        self._settings = settings
        self._file_repository = file_repository
        self._event_bus = event_bus
        self._lock = asyncio.Lock()
        self._retry_tasks: Dict[str, asyncio.Task] = {}

        logging.info("SpaceRetryManager initialiseret (Selvstændig med FileRepository)")

    async def schedule_space_retry(
        self, tracked_file: TrackedFile, space_check: SpaceCheckResult
    ) -> None:
        # In fail-and-rediscover strategy, all files that fail go directly to retry logic
        # No pause states exist - files either succeed, fail, or wait for space/network

        # Increment retry count for all space-related failures
        retry_count = await self.increment_retry_count(tracked_file.id)

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
        await self._update_file_status_and_notify(
            file_id=tracked_file.id,
            status=FileStatus.WAITING_FOR_SPACE,
            error_message=f"Temporary space shortage: {space_check.reason}. Retrying in {delay_seconds // 60} minutes.",
        )

        # Schedule retry using SpaceRetryManager
        success = await self.schedule_retry(
            tracked_file.id,
            delay_seconds,
            f"Temporary space shortage: {space_check.reason}",
            "space",
        )

        if success:
            logging.debug(
                f"SPACE RETRY SHORT: {tracked_file.file_path} [UUID: {tracked_file.id[:8]}...]"
            )
        else:
            logging.warning(
                f"Failed to schedule short retry for {tracked_file.file_path}"
            )

    async def _schedule_long_retry(
        self, tracked_file: TrackedFile, space_check: SpaceCheckResult
    ) -> None:
        delay_seconds = self._settings.space_retry_delay_seconds

        # Update file status to WAITING_FOR_SPACE
        await self._update_file_status_and_notify(
            file_id=tracked_file.id,
            status=FileStatus.WAITING_FOR_SPACE,
            error_message=f"Insufficient space: {space_check.reason}. Retrying in {delay_seconds // 60} minutes.",
        )

        # Schedule retry using SpaceRetryManager
        success = await self.schedule_retry(
            tracked_file.id,
            delay_seconds,
            f"Insufficient space: {space_check.reason}",
            "space",
        )

        if success:
            logging.debug(
                f"SPACE RETRY LONG: {tracked_file.file_path} [UUID: {tracked_file.id[:8]}...]"
            )
        else:
            logging.warning(
                f"Failed to schedule long retry for {tracked_file.file_path}"
            )

    async def _mark_as_permanent_space_error(
        self, tracked_file: TrackedFile, space_check: SpaceCheckResult
    ) -> None:
        if tracked_file:
            await self._update_file_status_and_notify(
                file_id=tracked_file.id,
                status=FileStatus.SPACE_ERROR,
                space_error_at=datetime.now(),
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


    async def cancel_all_retries(self) -> int:
        """Cancel all pending space retries."""
        logging.info("Cancelling all space retries")
        cancelled_count = 0
        async with self._lock:
            all_files = await self._file_repository.get_all()
            files_with_retries = [
                tracked_file.id
                for tracked_file in all_files
                if tracked_file.retry_info is not None
            ]
            for file_id in files_with_retries:
                if await self._cancel_existing_retry_unlocked(file_id):
                    cancelled_count += 1
        logging.info(f"Cancelled {cancelled_count} space retry operations")
        return cancelled_count

    async def schedule_retry(
        self, file_id: str, delay_seconds: int, reason: str, retry_type: str = "space"
    ) -> bool:
        async with self._lock:
            tracked_file = await self._file_repository.get_by_id(file_id)
            if not tracked_file:
                logging.warning(f"Cannot schedule retry for unknown file ID: {file_id}")
                return False
            await self._cancel_existing_retry_unlocked(file_id)
            now = datetime.now()
            tracked_file.retry_info = RetryInfo(
                scheduled_at=now,
                retry_at=now + timedelta(seconds=delay_seconds),
                reason=reason,
                retry_type=retry_type,
            )
            retry_task = asyncio.create_task(
                self._execute_retry_task(file_id, delay_seconds)
            )
            self._retry_tasks[file_id] = retry_task
            await self._file_repository.update(tracked_file)
            logging.info(
                f"Scheduled {retry_type} retry for {tracked_file.file_path} in {delay_seconds}s: {reason}"
            )
            return True

    async def cancel_retry(self, file_id: str) -> bool:
        async with self._lock:
            return await self._cancel_existing_retry_unlocked(file_id)

    async def _cancel_existing_retry_unlocked(self, file_id: str) -> bool:
        retry_cancelled = False
        if file_id in self._retry_tasks:
            task = self._retry_tasks.pop(file_id)
            task.cancel()
            retry_cancelled = True
            try:
                await asyncio.wait_for(task, timeout=0.1)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            except Exception as e:
                logging.warning(f"Error while cancelling task for {file_id}: {e}")
        tracked_file = await self._file_repository.get_by_id(file_id)
        if tracked_file and tracked_file.retry_info:
            tracked_file.retry_info = None
            await self._file_repository.update(tracked_file)
            retry_cancelled = True
        if retry_cancelled:
            logging.debug(f"Cancelled retry for file ID: {file_id}")
        return retry_cancelled

    async def _execute_retry_task(self, file_id: str, delay_seconds: int) -> None:
        try:
            await asyncio.sleep(delay_seconds)
            async with self._lock:
                tracked_file = await self._file_repository.get_by_id(file_id)
                if not tracked_file or not tracked_file.retry_info:
                    logging.debug(
                        f"Retry cancelled - file or retry info missing: {file_id}"
                    )
                    return
                if tracked_file.status != FileStatus.WAITING_FOR_SPACE:
                    logging.debug(
                        f"Retry cancelled - file status changed: {tracked_file.file_path} (status: {tracked_file.status.value})"
                    )
                    return
                tracked_file.status = FileStatus.READY
                tracked_file.error_message = None
                tracked_file.retry_info = None  # Clear retry info
                logging.info(
                    f"Retry executed for {tracked_file.file_path} - reset to READY"
                )
                self._retry_tasks.pop(file_id, None)
                await self._file_repository.update(tracked_file)

                # Publish status change event
                await self._event_bus.publish(
                    FileStatusChangedEvent(
                        file_id=tracked_file.id,
                        file_path=tracked_file.file_path,
                        old_status=FileStatus.WAITING_FOR_SPACE,
                        new_status=FileStatus.READY,
                        timestamp=datetime.now()
                    )
                )

        except asyncio.CancelledError:
            async with self._lock:
                self._retry_tasks.pop(file_id, None)
                tracked_file = await self._file_repository.get_by_id(file_id)
                if tracked_file:
                    tracked_file.retry_info = None
                    await self._file_repository.update(tracked_file)
            raise
        except Exception as e:
            logging.error(f"Error in retry task for file ID {file_id}: {e}")
            async with self._lock:
                tracked_file = await self._file_repository.get_by_id(file_id)
                if tracked_file:
                    tracked_file.retry_info = None
                    await self._file_repository.update(tracked_file)
                self._retry_tasks.pop(file_id, None)

    async def increment_retry_count(self, file_id: str) -> int:
        async with self._lock:
            tracked_file = await self._file_repository.get_by_id(file_id)
            if not tracked_file:
                logging.warning(
                    f"Cannot increment retry count for unknown file ID: {file_id}"
                )
                return 0
            tracked_file.retry_count += 1
            await self._file_repository.update(tracked_file)
            logging.debug(
                f"Incremented retry count for {tracked_file.file_path} to {tracked_file.retry_count}"
            )
            return tracked_file.retry_count

    async def _update_file_status_and_notify(
        self, file_id: str, status: FileStatus, **kwargs
    ) -> Optional[TrackedFile]:
        """Opdaterer filstatus, annullerer retries ved terminal-status og publicerer event."""
        async with self._lock:
            tracked_file = await self._file_repository.get_by_id(file_id)
            if not tracked_file:
                logging.warning(f"Forsøg på at opdatere ukendt fil ID: {file_id}")
                return None
            old_status = tracked_file.status
            if old_status == status:
                return tracked_file  # Ingen ændring
            logging.info(
                f"Status opdateret (RetryManager): {tracked_file.file_path} {old_status} -> {status}"
            )
            tracked_file.status = status
            # Håndter kwargs (f.eks. error_message, space_error_at)
            for key, value in kwargs.items():
                if hasattr(tracked_file, key):
                    setattr(tracked_file, key, value)
                else:
                    logging.warning(f"Ukendt attribut ignored: {key}")
            # Annuller retry-task, hvis filen når en terminal-status
            terminal_statuses = {FileStatus.FAILED, FileStatus.COMPLETED, FileStatus.REMOVED, FileStatus.SPACE_ERROR}
            if status in terminal_statuses:
                await self._cancel_existing_retry_unlocked(file_id)
            await self._file_repository.update(tracked_file)
        # Publicer event UDEN FOR LÅSEN
        await self._event_bus.publish(
            FileStatusChangedEvent(
                file_id=tracked_file.id,
                file_path=tracked_file.file_path,
                old_status=old_status,
                new_status=status,
                timestamp=datetime.now()
            )
        )
        return tracked_file
