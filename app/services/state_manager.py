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
from app.models import TrackedFile, FileStatus, FileStateUpdate, RetryInfo


class StateManager:
    def __init__(
        self, cooldown_minutes: int = 60, event_bus: Optional[DomainEventBus] = None
    ):
        self._files_by_id: Dict[str, TrackedFile] = {}
        self._lock = asyncio.Lock()
        self._subscribers: List[Callable[[FileStateUpdate], Awaitable[None]]] = []
        self._cooldown_minutes = cooldown_minutes
        self._event_bus = event_bus  # Event bus for decoupled communication

        # Retry task tracking - only tasks, state is in TrackedFile.retry_info
        self._retry_tasks: Dict[str, asyncio.Task] = {}

        if self._event_bus:
            asyncio.create_task(self._subscribe_to_events())

        logging.info("StateManager initialiseret")

    async def _subscribe_to_events(self):
        if not self._event_bus:
            return
        await self._event_bus.subscribe(
            FileDiscoveredEvent, self.handle_file_discovered
        )
        await self._event_bus.subscribe(
            FileStatusChangedEvent, self.handle_file_status_changed
        )
        logging.info("StateManager subscribed to domain events")

    async def handle_file_discovered(self, event: FileDiscoveredEvent) -> None:
        """Handles the FileDiscoveredEvent."""
        await self.add_file(
            file_path=event.file_path,
            file_size=event.file_size,
            last_write_time=datetime.fromtimestamp(event.last_write_time),
        )

    async def handle_file_status_changed(self, event: FileStatusChangedEvent) -> None:
        """Handles the FileStatusChangedEvent."""
        await self.update_file_status_by_id(file_id=event.file_id, status=event.new_status)

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

    def _get_active_file_for_path_internal(self, file_path: str) -> Optional[TrackedFile]:
        active_statuses = {
            FileStatus.DISCOVERED,
            FileStatus.READY,
            FileStatus.GROWING,
            FileStatus.READY_TO_START_GROWING,
            FileStatus.IN_QUEUE,
            FileStatus.COPYING,
            FileStatus.GROWING_COPY,
            FileStatus.WAITING_FOR_SPACE,
            FileStatus.SPACE_ERROR,
            FileStatus.WAITING_FOR_NETWORK,
        }
        candidates = [
            f
            for f in self._files_by_id.values()
            if f.file_path == file_path and f.status in active_statuses
        ]
        if not candidates:
            return None

        def sort_key(f: TrackedFile):
            active_priority = {
                FileStatus.COPYING: 1,
                FileStatus.IN_QUEUE: 2,
                FileStatus.GROWING_COPY: 3,
                FileStatus.READY_TO_START_GROWING: 4,
                FileStatus.READY: 5,
                FileStatus.GROWING: 6,
                FileStatus.DISCOVERED: 7,
                FileStatus.WAITING_FOR_SPACE: 8,
                FileStatus.WAITING_FOR_NETWORK: 8,
                FileStatus.SPACE_ERROR: 9,
            }
            priority = active_priority.get(f.status, 99)
            time_priority = -(
                f.discovered_at.timestamp() if f.discovered_at else 0
            )
            return (priority, time_priority)

        return min(candidates, key=sort_key)

    def _get_all_files_for_path(self, file_path: str) -> List[TrackedFile]:
        return [f for f in self._files_by_id.values() if f.file_path == file_path]

    async def add_file(
        self, file_path: str, file_size: int, last_write_time: Optional[datetime] = None
    ) -> TrackedFile:
        async with self._lock:
            existing_active = self._get_active_file_for_path_internal(file_path)
            if existing_active:
                logging.debug(f"Fil allerede tracked som aktiv: {file_path}")
                return existing_active
            any_existing = self._get_current_file_for_path(file_path)
            tracked_file = TrackedFile(
                file_path=file_path,
                file_size=file_size,
                last_write_time=last_write_time,
                status=FileStatus.DISCOVERED,
            )
            self._files_by_id[tracked_file.id] = tracked_file
            if any_existing and any_existing.status == FileStatus.REMOVED:
                logging.info(
                    f"File returned after REMOVED - creating new entry: {file_path}"
                )
                logging.info(
                    f"Previous REMOVED entry preserved as history: {any_existing.id}"
                )
            elif any_existing and any_existing.status in [
                FileStatus.COMPLETED,
                FileStatus.FAILED,
            ]:
                logging.info(
                    f"Ny fil med samme navn som completed/failed fil: {file_path} "
                    f"(Previous: {any_existing.id[:8]}..., New: {tracked_file.id[:8]}...)"
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

    def _is_space_error_in_cooldown(
        self, tracked_file: TrackedFile, cooldown_minutes: int = 60
    ) -> bool:
        if tracked_file.status != FileStatus.SPACE_ERROR:
            return False
        if not tracked_file.space_error_at:
            return False
        cooldown_duration = timedelta(minutes=cooldown_minutes)
        time_since_error = datetime.now() - tracked_file.space_error_at
        is_in_cooldown = time_since_error < cooldown_duration
        if is_in_cooldown:
            remaining_minutes = (
                cooldown_duration - time_since_error
            ).total_seconds() / 60
            logging.debug(
                f"File {tracked_file.file_path} in SPACE_ERROR cooldown - "
                f"{remaining_minutes:.1f} minutes remaining"
            )
        return is_in_cooldown

    async def should_skip_file_processing(
        self, file_path: str, cooldown_minutes: int = None
    ) -> bool:
        async with self._lock:
            existing_file = self._get_current_file_for_path(file_path)
            if not existing_file:
                return False
            if cooldown_minutes is None:
                cooldown_minutes = self._cooldown_minutes
            if existing_file.status == FileStatus.SPACE_ERROR:
                return self._is_space_error_in_cooldown(existing_file, cooldown_minutes)
            return False

    async def get_active_file_by_path(self, file_path: str) -> Optional[TrackedFile]:
        async with self._lock:
            active_statuses = {
                FileStatus.DISCOVERED,
                FileStatus.READY,
                FileStatus.GROWING,
                FileStatus.READY_TO_START_GROWING,
                FileStatus.IN_QUEUE,
                FileStatus.COPYING,
                FileStatus.GROWING_COPY,
                FileStatus.WAITING_FOR_SPACE,
                FileStatus.WAITING_FOR_NETWORK,
                FileStatus.SPACE_ERROR,
            }
            candidates = [
                f
                for f in self._files_by_id.values()
                if f.file_path == file_path and f.status in active_statuses
            ]
            if not candidates:
                return None

            def sort_key(f: TrackedFile):
                active_priority = {
                    FileStatus.COPYING: 1,
                    FileStatus.IN_QUEUE: 2,
                    FileStatus.GROWING_COPY: 3,
                    FileStatus.READY_TO_START_GROWING: 4,
                    FileStatus.READY: 5,
                    FileStatus.GROWING: 6,
                    FileStatus.DISCOVERED: 7,
                    FileStatus.WAITING_FOR_SPACE: 8,
                    FileStatus.WAITING_FOR_NETWORK: 8,
                    FileStatus.SPACE_ERROR: 9,
                }
                priority = active_priority.get(f.status, 99)
                time_priority = -(
                    f.discovered_at.timestamp() if f.discovered_at else 0
                )
                return (priority, time_priority)

            return min(candidates, key=sort_key)

    async def get_all_files(self) -> List[TrackedFile]:
        async with self._lock:
            return list(self._files_by_id.values())

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
                    tracked_file.completed_at
                    or tracked_file.failed_at
                    or tracked_file.discovered_at
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
            result = self._files_by_id.get(file_id)
            if not result:
                logging.debug(
                    f"🔍 get_file_by_id: UUID {file_id[:8]}... not found in {len(self._files_by_id)} files"
                )
            return result

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
        status_changed = False
        event_to_publish = None
        async with self._lock:
            tracked_file = self._files_by_id.get(file_id)
            if not tracked_file:
                logging.warning(f"Forsøg på at opdatere ukendt fil ID: {file_id}")
                return None
            old_status = tracked_file.status
            if old_status != status:
                status_changed = True
                logging.info(
                    f"Status opdateret (ID): {tracked_file.file_path} {old_status} -> {status}"
                )
                if self._event_bus:
                    event_to_publish = FileStatusChangedEvent(
                        file_id=tracked_file.id,
                        file_path=tracked_file.file_path,
                        old_status=old_status,
                        new_status=status,
                    )
                    if status == FileStatus.READY:
                        ready_event = FileReadyEvent(
                            file_id=tracked_file.id, file_path=tracked_file.file_path
                        )
                        asyncio.create_task(self._event_bus.publish(ready_event))
            tracked_file.status = status
            terminal_statuses = {FileStatus.FAILED, FileStatus.COMPLETED, FileStatus.REMOVED}
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
        await self._notify(
            FileStateUpdate(
                file_path=tracked_file.file_path,
                old_status=old_status,
                new_status=status,
                tracked_file=tracked_file,
            )
        )
        if event_to_publish:
            await self._event_bus.publish(event_to_publish)
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
                if f.status
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

    async def is_file_stable(self, file_id: str, stable_time_seconds: int) -> bool:
        async with self._lock:
            tracked_file = self._files_by_id.get(file_id)
            if not tracked_file:
                return False
            now = datetime.now()
            time_since_discovery = now - tracked_file.discovered_at
            stable_duration = timedelta(seconds=stable_time_seconds)
            is_stable = time_since_discovery >= stable_duration
            if is_stable:
                logging.debug(
                    f"File is stable: {tracked_file.file_path} (stable for {time_since_discovery.total_seconds():.1f}s)"
                )
            return is_stable

    async def update_file_metadata(
        self, file_id: str, new_size: int, new_write_time: datetime
    ) -> bool:
        async with self._lock:
            tracked_file = self._files_by_id.get(file_id)
            if not tracked_file:
                logging.warning(
                    f"Attempted to update metadata for unknown file ID: {file_id}"
                )
                return False
            size_changed = tracked_file.file_size != new_size
            time_changed = tracked_file.last_write_time != new_write_time
            if size_changed or time_changed:
                old_size = tracked_file.file_size
                tracked_file.file_size = new_size
                tracked_file.last_write_time = new_write_time
                tracked_file.discovered_at = datetime.now()  # Reset stability timer
                logging.info(
                    f"File changed, resetting stability timer: {tracked_file.file_path} "
                    f"(size: {old_size} -> {new_size}, write_time updated)"
                )
                await self._notify(
                    FileStateUpdate(
                        file_path=tracked_file.file_path,
                        old_status=tracked_file.status,
                        new_status=tracked_file.status,
                        tracked_file=tracked_file,
                    )
                )
                return True  # File changed
            return False  # No change detected

    async def schedule_retry(
        self, file_id: str, delay_seconds: int, reason: str, retry_type: str = "space"
    ) -> bool:
        async with self._lock:
            tracked_file = self._files_by_id.get(file_id)
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
        tracked_file = self._files_by_id.get(file_id)
        if tracked_file and tracked_file.retry_info:
            tracked_file.retry_info = None
            retry_cancelled = True
        if retry_cancelled:
            logging.debug(f"Cancelled retry for file ID: {file_id}")
        return retry_cancelled

    async def _execute_retry_task(self, file_id: str, delay_seconds: int) -> None:
        try:
            await asyncio.sleep(delay_seconds)
            async with self._lock:
                tracked_file = self._files_by_id.get(file_id)
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
                old_status = tracked_file.status
                tracked_file.status = FileStatus.READY
                tracked_file.error_message = None
                tracked_file.retry_info = None  # Clear retry info
                logging.info(
                    f"Retry executed for {tracked_file.file_path} - reset to READY"
                )
                self._retry_tasks.pop(file_id, None)
                await self._notify(
                    FileStateUpdate(
                        file_path=tracked_file.file_path,
                        old_status=old_status,
                        new_status=FileStatus.READY,
                        tracked_file=tracked_file,
                    )
                )
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
                tracked_file = self._files_by_id.get(file_id)
                if tracked_file:
                    tracked_file.retry_info = None
                self._retry_tasks.pop(file_id, None)

    async def get_retry_info(self, file_id: str) -> Optional[RetryInfo]:
        async with self._lock:
            tracked_file = self._files_by_id.get(file_id)
            return tracked_file.retry_info if tracked_file else None

    async def cancel_all_retries(self) -> int:
        async with self._lock:
            cancelled_count = 0
            files_with_retries = [
                file_id
                for file_id, tracked_file in self._files_by_id.items()
                if tracked_file.retry_info is not None
            ]
            for file_id in files_with_retries:
                if await self._cancel_existing_retry_unlocked(file_id):
                    cancelled_count += 1
            logging.info(f"Cancelled {cancelled_count} pending retries")
            return cancelled_count

    async def increment_retry_count(self, file_id: str) -> int:
        async with self._lock:
            tracked_file = self._files_by_id.get(file_id)
            if not tracked_file:
                logging.warning(
                    f"Cannot increment retry count for unknown file ID: {file_id}"
                )
                return 0
            tracked_file.retry_count += 1
            logging.debug(
                f"Incremented retry count for {tracked_file.file_path} to {tracked_file.retry_count}"
            )
            return tracked_file.retry_count