import asyncio
import logging
from datetime import datetime
from typing import List, Optional, Callable, Awaitable

from app.core.file_repository import FileRepository
from app.models import TrackedFile, FileStatus, FileStateUpdate


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



