import asyncio
import logging
from typing import Dict, List, Optional, Set, Callable, Awaitable
from datetime import datetime, timedelta

from app.models import TrackedFile, FileStatus, FileStateUpdate


class StateManager:
    def __init__(self):
        self._files_by_id: Dict[str, TrackedFile] = {}
        self._lock = asyncio.Lock()
        self._subscribers: List[Callable[[FileStateUpdate], Awaitable[None]]] = []

        logging.info("StateManager initialiseret")

    def _get_current_file_for_path(self, file_path: str) -> Optional[TrackedFile]:
        candidates = [f for f in self._files_by_id.values() if f.file_path == file_path]
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
                FileStatus.PAUSED_COPYING: 8,
                FileStatus.PAUSED_IN_QUEUE: 9,
                FileStatus.PAUSED_GROWING_COPY: 10,
                FileStatus.WAITING_FOR_SPACE: 11,
                FileStatus.COMPLETED: 12,
                FileStatus.FAILED: 13,
                FileStatus.REMOVED: 14,
                FileStatus.SPACE_ERROR: 15,
            }

            priority = active_statuses.get(f.status, 99)
            time_priority = -(f.discovered_at.timestamp() if f.discovered_at else 0)
            return (priority, time_priority)

        return min(candidates, key=sort_key)

    def _get_all_files_for_path(self, file_path: str) -> List[TrackedFile]:
        return [f for f in self._files_by_id.values() if f.file_path == file_path]

    async def add_file(
        self, file_path: str, file_size: int, last_write_time: Optional[datetime] = None
    ) -> TrackedFile:
        async with self._lock:
            existing = self._get_current_file_for_path(file_path)
            if existing and existing.status != FileStatus.REMOVED:
                logging.debug(f"Fil allerede tracked: {file_path}")
                return existing

            tracked_file = TrackedFile(
                file_path=file_path,
                file_size=file_size,
                last_write_time=last_write_time,
                status=FileStatus.DISCOVERED,
            )

            self._files_by_id[tracked_file.id] = tracked_file

            if existing and existing.status == FileStatus.REMOVED:
                logging.info(
                    f"File returned after REMOVED - creating new entry: {file_path}"
                )
                logging.info(
                    f"Previous REMOVED entry preserved as history: {existing.id}"
                )
            else:
                logging.info(f"Ny fil tilføjet: {file_path} ({file_size} bytes)")

        await self._notify(
            FileStateUpdate(
                file_path=file_path,
                old_status=None,
                new_status=FileStatus.DISCOVERED,
                tracked_file=tracked_file,
            )
        )

        return tracked_file

    async def get_file_by_path(self, file_path: str) -> Optional[TrackedFile]:
        async with self._lock:
            current_file = self._get_current_file_for_path(file_path)
            if current_file and current_file.status == FileStatus.REMOVED:
                return None
            return current_file

    async def get_all_files(self) -> List[TrackedFile]:
        async with self._lock:
            return list(self._files_by_id.values())

    async def get_current_files_only(self) -> List[TrackedFile]:
        async with self._lock:
            current_files = {}
            for tracked_file in self._files_by_id.values():
                if tracked_file.status == FileStatus.REMOVED:
                    continue

                current = current_files.get(tracked_file.file_path)
                if not current or self._is_more_current(tracked_file, current):
                    current_files[tracked_file.file_path] = tracked_file

            return list(current_files.values())

    def _is_more_current(self, file1: TrackedFile, file2: TrackedFile) -> bool:
        active_statuses = {
            FileStatus.COPYING: 1,
            FileStatus.IN_QUEUE: 2,
            FileStatus.GROWING_COPY: 3,
            FileStatus.READY_TO_START_GROWING: 4,
            FileStatus.READY: 5,
            FileStatus.GROWING: 6,
            FileStatus.DISCOVERED: 7,
            FileStatus.PAUSED_COPYING: 8,
            FileStatus.PAUSED_IN_QUEUE: 9,
            FileStatus.PAUSED_GROWING_COPY: 10,
            FileStatus.WAITING_FOR_SPACE: 11,
            FileStatus.COMPLETED: 12,
            FileStatus.FAILED: 13,
            FileStatus.REMOVED: 14,
            FileStatus.SPACE_ERROR: 15,
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
            for tracked_file in self._files_by_id.values():
                if tracked_file.status == status:
                    current = current_files.get(tracked_file.file_path)
                    if not current or self._is_more_current(tracked_file, current):
                        current_files[tracked_file.file_path] = tracked_file

            return list(current_files.values())

    async def cleanup_missing_files(self, existing_paths: Set[str]) -> int:
        removed_count = 0

        async with self._lock:
            current_files = {}
            for tracked_file in self._files_by_id.values():
                current = current_files.get(tracked_file.file_path)
                if not current or self._is_more_current(tracked_file, current):
                    current_files[tracked_file.file_path] = tracked_file

            for file_path, tracked_file in current_files.items():
                if file_path not in existing_paths:
                    if tracked_file.status == FileStatus.COMPLETED:
                        logging.debug(f"Bevarer completed fil i memory: {file_path}")
                        continue

                    if tracked_file.status in [
                        FileStatus.COPYING,
                        FileStatus.IN_QUEUE,
                        FileStatus.GROWING_COPY,
                    ]:
                        logging.debug(
                            f"Bevarer fil under processing: {file_path} (status: {tracked_file.status})"
                        )
                        continue

                    if tracked_file.status != FileStatus.REMOVED:
                        old_status = tracked_file.status
                        tracked_file.status = FileStatus.REMOVED
                        removed_count += 1
                        logging.info(
                            f"Marked missing file as REMOVED: {file_path} (was {old_status})"
                        )

        if removed_count > 0:
            logging.info(
                f"Cleanup: Markerede {removed_count} manglende filer som REMOVED"
            )

        return removed_count

    async def cleanup_old_files(self, max_age_hours: int) -> int:
        removed_count = 0
        now = datetime.now()
        cutoff_time = now - timedelta(hours=max_age_hours)

        async with self._lock:
            to_remove_ids = []
            
            for file_id, tracked_file in self._files_by_id.items():
                file_age_timestamp = (
                    tracked_file.completed_at or 
                    tracked_file.failed_at or 
                    tracked_file.discovered_at
                )
                
                if file_age_timestamp and file_age_timestamp < cutoff_time:
                    to_remove_ids.append(file_id)

            for file_id in to_remove_ids:
                if file_id in self._files_by_id:
                    removed_file = self._files_by_id.pop(file_id)
                    removed_count += 1
                    logging.debug(
                        f"Cleanup: Removed old file: {removed_file.file_path} "
                        f"(status: {removed_file.status})"
                    )

        if removed_count > 0:
            logging.info(
                f"Cleanup: Fjernede {removed_count} gamle filer fra memory "
                f"(ældre end {max_age_hours} timer)"
            )

        return removed_count

    def subscribe(self, callback: Callable[[FileStateUpdate], Awaitable[None]]) -> None:
        self._subscribers.append(callback)
        logging.debug(f"Ny subscriber tilmeldt. Total: {len(self._subscribers)}")

    def unsubscribe(
        self, callback: Callable[[FileStateUpdate], Awaitable[None]]
    ) -> bool:
        try:
            self._subscribers.remove(callback)
            logging.debug(f"Subscriber afmeldt. Total: {len(self._subscribers)}")
            return True
        except ValueError:
            return False

    async def get_file_by_id(self, file_id: str) -> Optional[TrackedFile]:
        async with self._lock:
            return self._files_by_id.get(file_id)

    async def get_file_history(self, file_path: str) -> List[TrackedFile]:
        async with self._lock:
            files = self._get_all_files_for_path(file_path)
            return sorted(files, key=lambda f: f.discovered_at, reverse=True)

    async def remove_file_by_id(self, file_id: str) -> bool:
        async with self._lock:
            if file_id in self._files_by_id:
                self._files_by_id.pop(file_id)
                logging.debug(f"Permanently removed file by ID: {file_id}")
                return True
            return False

    async def update_file_status_by_id(
        self, file_id: str, status: FileStatus, **kwargs
    ) -> Optional[TrackedFile]:
        async with self._lock:
            tracked_file = self._files_by_id.get(file_id)
            if not tracked_file:
                logging.warning(f"Forsøg på at opdatere ukendt fil ID: {file_id}")
                return None

            old_status = tracked_file.status
            tracked_file.status = status

            if status == FileStatus.READY_TO_START_GROWING:
                tracked_file.is_growing_file = True
            elif status in [FileStatus.READY, FileStatus.COMPLETED]:
                if "is_growing_file" not in kwargs:
                    tracked_file.is_growing_file = False

            for key, value in kwargs.items():
                if hasattr(tracked_file, key):
                    setattr(tracked_file, key, value)
                else:
                    logging.warning(f"Ukendt attribut ignored: {key}")

            if status == FileStatus.COPYING and not tracked_file.started_copying_at:
                tracked_file.started_copying_at = datetime.now()
            elif status == FileStatus.COMPLETED and not tracked_file.completed_at:
                tracked_file.completed_at = datetime.now()
            elif status == FileStatus.FAILED and not getattr(tracked_file, 'failed_at', None):
                tracked_file.failed_at = datetime.now()

            if old_status != status:
                logging.info(
                    f"Status opdateret (ID): {tracked_file.file_path} {old_status} -> {status}"
                )

        await self._notify(
            FileStateUpdate(
                file_path=tracked_file.file_path,
                old_status=old_status,
                new_status=status,
                tracked_file=tracked_file,
            )
        )

        return tracked_file

    async def _notify(self, update: FileStateUpdate) -> None:
        if not self._subscribers:
            return

        tasks = []
        for callback in self._subscribers:
            try:
                task = asyncio.create_task(callback(update))
                tasks.append(task)
            except Exception as e:
                logging.error(f"Fejl ved oprettelse af subscriber task: {e}")

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logging.error(f"Subscriber {i} fejlede: {result}")

    async def get_statistics(self) -> Dict:
        async with self._lock:
            current_files = {}
            for tracked_file in self._files_by_id.values():
                current = current_files.get(tracked_file.file_path)
                if not current or self._is_more_current(tracked_file, current):
                    current_files[tracked_file.file_path] = tracked_file

            current_files_list = list(current_files.values())
            total_files = len(current_files_list)
            status_counts = {}

            for status in FileStatus:
                status_counts[status.value] = len(
                    [f for f in current_files_list if f.status == status]
                )

            total_size = sum(f.file_size for f in current_files_list)

            copying_files = [
                f for f in current_files_list if f.status == FileStatus.COPYING
            ]

            growing_files = [
                f
                for f in current_files_list
                if f.is_growing_file
                or f.status
                in [
                    FileStatus.GROWING,
                    FileStatus.READY_TO_START_GROWING,
                    FileStatus.GROWING_COPY,
                ]
            ]

            return {
                "total_files": total_files,
                "status_counts": status_counts,
                "total_size_bytes": total_size,
                "active_copies": len(copying_files),
                "growing_files": len(growing_files),
                "subscribers": len(self._subscribers),
            }

    async def get_active_copy_files(self) -> List[TrackedFile]:
        async with self._lock:
            current_files = {}
            for tracked_file in self._files_by_id.values():
                if tracked_file.status in [
                    FileStatus.IN_QUEUE,
                    FileStatus.COPYING,
                    FileStatus.GROWING_COPY,
                ]:
                    current = current_files.get(tracked_file.file_path)
                    if not current or self._is_more_current(tracked_file, current):
                        current_files[tracked_file.file_path] = tracked_file

            return list(current_files.values())

    async def get_paused_files(self) -> List[TrackedFile]:
        async with self._lock:
            current_files = {}
            paused_statuses = [
                FileStatus.PAUSED_IN_QUEUE,
                FileStatus.PAUSED_COPYING,
                FileStatus.PAUSED_GROWING_COPY,
            ]

            for tracked_file in self._files_by_id.values():
                if tracked_file.status in paused_statuses:
                    current = current_files.get(tracked_file.file_path)
                    if not current or self._is_more_current(tracked_file, current):
                        current_files[tracked_file.file_path] = tracked_file

            return list(current_files.values())
