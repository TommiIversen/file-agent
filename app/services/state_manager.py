import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Callable, Awaitable

from app.core.events.event_bus import DomainEventBus
from app.core.events.file_events import (
    FileDiscoveredEvent,
    FileStatusChangedEvent,
    FileReadyEvent,
)
from app.core.file_repository import FileRepository
from app.models import TrackedFile, FileStatus, FileStateUpdate, RetryInfo


class StateManager:
    def __init__(
        self,
        file_repository: FileRepository,
        cooldown_minutes: int = 60,
    ):
        self._file_repository = file_repository
        self._lock = asyncio.Lock()
        self._subscribers: List[Callable[[FileStateUpdate], Awaitable[None]]] = []
        self._cooldown_minutes = cooldown_minutes

        # Retry task tracking - only tasks, state is in TrackedFile.retry_info
        self._retry_tasks: Dict[str, asyncio.Task] = {}

        logging.info("StateManager initialiseret med FileRepository")


    async def _get_current_file_for_path(self, file_path: str) -> Optional[TrackedFile]:
        all_files = await self._file_repository.get_all()
        candidates = [f for f in all_files if f.file_path == file_path]
        if not candidates:
            return None

        def sort_key(f: TrackedFile):
            active_statuses = {
                FileStatus.COPYING: 1,
                FileStatus.IN_QUEUE: 2,
                FileStatus.GROWING_COPY: 3,
                FileStatus.READY_TO_START_GROWING: 4,
                FileStatus.READY: 5,
                FileStatus.GROWING: 6,
                FileStatus.DISCOVERED: 7,
                FileStatus.WAITING_FOR_SPACE: 8,
                FileStatus.WAITING_FOR_NETWORK: 9,
                FileStatus.COMPLETED: 10,
                FileStatus.FAILED: 11,
                FileStatus.REMOVED: 12,
                FileStatus.SPACE_ERROR: 13,
            }

            priority = active_statuses.get(f.status, 99)
            time_priority = -(f.discovered_at.timestamp() if f.discovered_at else 0)
            return (priority, time_priority)

        return min(candidates, key=sort_key)


    async def get_file_by_path(self, file_path: str) -> Optional[TrackedFile]:
        async with self._lock:
            current_file = await self._get_current_file_for_path(file_path)
            if current_file and current_file.status == FileStatus.REMOVED:
                return None
            return current_file

    def _is_more_current(self, file1: TrackedFile, file2: TrackedFile) -> bool:
        active_statuses = {
            FileStatus.COPYING: 1,
            FileStatus.IN_QUEUE: 2,
            FileStatus.GROWING_COPY: 3,
            FileStatus.READY_TO_START_GROWING: 4,
            FileStatus.READY: 5,
            FileStatus.GROWING: 6,
            FileStatus.DISCOVERED: 7,
            FileStatus.WAITING_FOR_SPACE: 8,
            FileStatus.WAITING_FOR_NETWORK: 8,
            FileStatus.COMPLETED: 9,
            FileStatus.FAILED: 10,
            FileStatus.REMOVED: 11,
            FileStatus.SPACE_ERROR: 12,
        }
        priority1 = active_statuses.get(file1.status, 99)
        priority2 = active_statuses.get(file2.status, 99)
        if priority1 != priority2:
            return priority1 < priority2
        time1 = file1.discovered_at.timestamp() if file1.discovered_at else 0
        time2 = file2.discovered_at.timestamp() if file2.discovered_at else 0
        return time1 > time2

    async def get_files_by_status(self, status: FileStatus) -> List[TrackedFile]:
        async with self._lock:
            current_files = {}
            all_files = await self._file_repository.get_all()
            for tracked_file in all_files:
                if tracked_file.status == status:
                    current = current_files.get(tracked_file.file_path)
                    if not current or self._is_more_current(tracked_file, current):
                        current_files[tracked_file.file_path] = tracked_file
            return list(current_files.values())



    async def get_file_by_id(self, file_id: str) -> Optional[TrackedFile]:
        async with self._lock:
            result = await self._file_repository.get_by_id(file_id)
            if not result:
                all_files_count = await self._file_repository.count()
                logging.debug(
                    f"🔍 get_file_by_id: UUID {file_id[:8]}... not found in {all_files_count} files"
                )
            return result

    async def update_file_status_by_id(
        self, file_id: str, status: FileStatus, **kwargs
    ) -> Optional[TrackedFile]:
        async with self._lock:
            tracked_file = await self._file_repository.get_by_id(file_id)
            if not tracked_file:
                logging.warning(f"Forsøg på at opdatere ukendt fil ID: {file_id}")
                return None
            old_status = tracked_file.status
            if old_status != status:
                logging.info(
                    f"Status opdateret (ID): {tracked_file.file_path} {old_status} -> {status}"
                )
 
            tracked_file.status = status
            terminal_statuses = {
                FileStatus.FAILED,
                FileStatus.COMPLETED,
                FileStatus.REMOVED,
            }
            if status in terminal_statuses:
                await self._cancel_existing_retry_unlocked(file_id)
                logging.debug(
                    f"RETRY CANCELLED: File {tracked_file.file_path} reached terminal status {status.value} - "
                    f"cancelled scheduled retry [UUID: {file_id[:8]}...]"
                )
            for key, value in kwargs.items():
                if hasattr(tracked_file, key):
                    setattr(tracked_file, key, value)
                else:
                    logging.warning(f"Ukendt attribut ignored: {key}")
            if status == FileStatus.COPYING and not tracked_file.started_copying_at:
                tracked_file.started_copying_at = datetime.now()
            elif status == FileStatus.COMPLETED and not tracked_file.completed_at:
                tracked_file.completed_at = datetime.now()
            elif status == FileStatus.FAILED and not getattr(
                tracked_file, "failed_at", None
            ):
                tracked_file.failed_at = datetime.now()
            
            await self._file_repository.update(tracked_file)

        return tracked_file


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

        except asyncio.CancelledError:
            async with self._lock:
                tracked_file = self._files_by_id.get(file_id)
                if tracked_file:
                    tracked_file.retry_info = None
                self._retry_tasks.pop(file_id, None)
            raise
        except Exception as e:
            logging.error(f"Error in retry task for file ID {file_id}: {e}")
            async with self._lock:
                tracked_file = await self._file_repository.get_by_id(file_id)
                if tracked_file:
                    tracked_file.retry_info = None
                    await self._file_repository.add(tracked_file)
                self._retry_tasks.pop(file_id, None)

    async def cancel_all_retries(self) -> int:
        async with self._lock:
            cancelled_count = 0
            all_files = await self._file_repository.get_all()
            files_with_retries = [
                tracked_file.id
                for tracked_file in all_files
                if tracked_file.retry_info is not None
            ]
            for file_id in files_with_retries:
                if await self._cancel_existing_retry_unlocked(file_id):
                    cancelled_count += 1
            logging.info(f"Cancelled {cancelled_count} pending retries")
            return cancelled_count

    async def increment_retry_count(self, file_id: str) -> int:
        async with self._lock:
            tracked_file = await self._file_repository.get_by_id(file_id)
            if not tracked_file:
                logging.warning(
                    f"Cannot increment retry count for unknown file ID: {file_id}"
                )
                return 0
            tracked_file.retry_count += 1
            await self._file_repository.add(tracked_file)
            logging.debug(
                f"Incremented retry count for {tracked_file.file_path} to {tracked_file.retry_count}"
            )
            return tracked_file.retry_count
