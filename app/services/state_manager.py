import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Callable, Awaitable

from app.models import TrackedFile, FileStatus, FileStateUpdate, RetryInfo


class StateManager:
    def __init__(self, cooldown_minutes: int = 60):
        self._files_by_id: Dict[str, TrackedFile] = {}
        self._lock = asyncio.Lock()
        self._subscribers: List[Callable[[FileStateUpdate], Awaitable[None]]] = []
        self._cooldown_minutes = cooldown_minutes
        
        # Retry task tracking - only tasks, state is in TrackedFile.retry_info
        self._retry_tasks: Dict[str, asyncio.Task] = {}

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

    def _get_active_file_for_path_internal(self, file_path: str) -> Optional[TrackedFile]:
        """Internal version of get_active_file_by_path without async lock"""
        # Find kun filer der ikke er completed, failed eller removed
        active_statuses = {
            FileStatus.DISCOVERED,
            FileStatus.READY,
            FileStatus.GROWING,
            FileStatus.READY_TO_START_GROWING,
            FileStatus.IN_QUEUE,
            FileStatus.COPYING,
            FileStatus.GROWING_COPY,
            FileStatus.PAUSED_COPYING,
            FileStatus.PAUSED_IN_QUEUE,
            FileStatus.PAUSED_GROWING_COPY,
            FileStatus.WAITING_FOR_SPACE,
            FileStatus.SPACE_ERROR,
        }
        
        candidates = [
            f for f in self._files_by_id.values() 
            if f.file_path == file_path and f.status in active_statuses
        ]
        
        if not candidates:
            return None
            
        # Returner den med højeste prioritet blandt aktive filer
        def sort_key(f: TrackedFile):
            active_priority = {
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
                FileStatus.SPACE_ERROR: 12,
            }
            
            priority = active_priority.get(f.status, 99)
            time_priority = -(f.discovered_at.timestamp() if f.discovered_at else 0)
            return (priority, time_priority)
        
        return min(candidates, key=sort_key)

    def _get_all_files_for_path(self, file_path: str) -> List[TrackedFile]:
        return [f for f in self._files_by_id.values() if f.file_path == file_path]

    async def add_file(
            self, file_path: str, file_size: int, last_write_time: Optional[datetime] = None
    ) -> TrackedFile:
        async with self._lock:
            # Check for existing ACTIVE files only - ignore completed/failed files
            # Dette sikrer at completed files ikke forhindrer nye filer med samme navn
            existing_active = self._get_active_file_for_path_internal(file_path)
            if existing_active:
                logging.debug(f"Fil allerede tracked som aktiv: {file_path}")
                return existing_active

            # Check hvis der var en removed/completed fil tidligere (BEFORE adding new file)
            # Dette skal gøres FØR den nye fil tilføjes, ellers vil _get_current_file_for_path 
            # returnere den nye fil i stedet for den gamle
            any_existing = self._get_current_file_for_path(file_path)

            tracked_file = TrackedFile(
                file_path=file_path,
                file_size=file_size,
                last_write_time=last_write_time,
                status=FileStatus.DISCOVERED,
            )

            self._files_by_id[tracked_file.id] = tracked_file

            # Log appropriate message based on previous file status
            if any_existing and any_existing.status == FileStatus.REMOVED:
                logging.info(
                    f"File returned after REMOVED - creating new entry: {file_path}"
                )
                logging.info(
                    f"Previous REMOVED entry preserved as history: {any_existing.id}"
                )
            elif any_existing and any_existing.status in [FileStatus.COMPLETED, FileStatus.FAILED]:
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

    def _is_space_error_in_cooldown(self, tracked_file: TrackedFile, cooldown_minutes: int = 60) -> bool:
        """
        Check if a file with SPACE_ERROR status is still in cooldown period.
        
        Args:
            tracked_file: The TrackedFile to check
            cooldown_minutes: Cooldown period in minutes (default 60)
            
        Returns:
            True if file is in cooldown, False otherwise
        """
        if tracked_file.status != FileStatus.SPACE_ERROR:
            return False
            
        if not tracked_file.space_error_at:
            # No timestamp set, allow processing (shouldn't happen but be safe)
            return False
            
        cooldown_duration = timedelta(minutes=cooldown_minutes)
        time_since_error = datetime.now() - tracked_file.space_error_at
        
        is_in_cooldown = time_since_error < cooldown_duration
        
        if is_in_cooldown:
            remaining_minutes = (cooldown_duration - time_since_error).total_seconds() / 60
            logging.debug(
                f"File {tracked_file.file_path} in SPACE_ERROR cooldown - "
                f"{remaining_minutes:.1f} minutes remaining"
            )
        
        return is_in_cooldown

    async def should_skip_file_processing(self, file_path: str, cooldown_minutes: int = None) -> bool:
        """
        Check if a file should be skipped for processing due to cooldown or other conditions.
        
        Args:
            file_path: Path to the file to check
            cooldown_minutes: Override cooldown period (uses config default if None)
            
        Returns:
            True if file should be skipped, False if it can be processed
        """
        async with self._lock:
            existing_file = self._get_current_file_for_path(file_path)
            if not existing_file:
                return False
                
            # Use config value if not specified
            if cooldown_minutes is None:
                cooldown_minutes = self._cooldown_minutes
                
            # Skip if file is in SPACE_ERROR cooldown
            if existing_file.status == FileStatus.SPACE_ERROR:
                return self._is_space_error_in_cooldown(existing_file, cooldown_minutes)
                
            return False

    async def get_active_file_by_path(self, file_path: str) -> Optional[TrackedFile]:
        """
        Hent aktiv fil for en given path - ignorerer completed og failed files.
        
        Denne metode bruges af file scanner for at undgå at genbruge completed files
        når en ny fil med samme navn bliver opdaget.
        """
        async with self._lock:
            # Find kun filer der ikke er completed, failed eller removed
            active_statuses = {
                FileStatus.DISCOVERED,
                FileStatus.READY,
                FileStatus.GROWING,
                FileStatus.READY_TO_START_GROWING,
                FileStatus.IN_QUEUE,
                FileStatus.COPYING,
                FileStatus.GROWING_COPY,
                FileStatus.PAUSED_COPYING,
                FileStatus.PAUSED_IN_QUEUE,
                FileStatus.PAUSED_GROWING_COPY,
                FileStatus.WAITING_FOR_SPACE,
                FileStatus.SPACE_ERROR,
            }
            
            candidates = [
                f for f in self._files_by_id.values() 
                if f.file_path == file_path and f.status in active_statuses
            ]
            
            if not candidates:
                return None
                
            # Returner den med højeste prioritet blandt aktive filer
            def sort_key(f: TrackedFile):
                active_priority = {
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
                    FileStatus.SPACE_ERROR: 12,
                }
                
                priority = active_priority.get(f.status, 99)
                time_priority = -(f.discovered_at.timestamp() if f.discovered_at else 0)
                return (priority, time_priority)
            
            return min(candidates, key=sort_key)

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

    async def is_file_stable(self, file_id: str, stable_time_seconds: int) -> bool:
        """
        Check if file has been stable for required duration.
        
        A file is considered stable when it hasn't changed (size or write time)
        for at least stable_time_seconds since it was discovered or last changed.
        """
        async with self._lock:
            tracked_file = self._files_by_id.get(file_id)
            if not tracked_file:
                return False
            
            # Check if file has been unchanged since discovery/last change
            now = datetime.now()
            time_since_discovery = now - tracked_file.discovered_at
            stable_duration = timedelta(seconds=stable_time_seconds)
            
            is_stable = time_since_discovery >= stable_duration
            
            if is_stable:
                logging.debug(f"File is stable: {tracked_file.file_path} (stable for {time_since_discovery.total_seconds():.1f}s)")
            
            return is_stable

    async def update_file_metadata(self, file_id: str, new_size: int, 
                                 new_write_time: datetime) -> bool:
        """
        Update file metadata and reset stability timer if file has changed.
        
        Returns True if file has changed (requiring stability timer reset),
        False if no changes detected.
        """
        async with self._lock:
            tracked_file = self._files_by_id.get(file_id)
            if not tracked_file:
                logging.warning(f"Attempted to update metadata for unknown file ID: {file_id}")
                return False
            
            # Check if file has changed
            size_changed = tracked_file.file_size != new_size
            time_changed = tracked_file.last_write_time != new_write_time
            
            if size_changed or time_changed:
                # File has changed - update metadata and reset stability timer
                old_size = tracked_file.file_size
                tracked_file.file_size = new_size
                tracked_file.last_write_time = new_write_time
                tracked_file.discovered_at = datetime.now()  # Reset stability timer
                
                logging.info(f"File changed, resetting stability timer: {tracked_file.file_path} "
                           f"(size: {old_size} -> {new_size}, write_time updated)")
                
                # Notify subscribers of the change
                await self._notify(
                    FileStateUpdate(
                        file_path=tracked_file.file_path,
                        old_status=tracked_file.status,
                        new_status=tracked_file.status,  # Status unchanged, but metadata updated
                        tracked_file=tracked_file,
                    )
                )
                
                return True  # File changed
            
            return False  # No change detected

    async def schedule_retry(self, file_id: str, delay_seconds: int, reason: str, 
                           retry_type: str = "space") -> bool:
        """
        Schedule a retry operation for a file.
        
        Returns True if retry was successfully scheduled, False if file not found.
        """
        async with self._lock:
            tracked_file = self._files_by_id.get(file_id)
            if not tracked_file:
                logging.warning(f"Cannot schedule retry for unknown file ID: {file_id}")
                return False
            
            # Cancel any existing retry for this file
            await self._cancel_existing_retry_unlocked(file_id)
            
            # Create retry info and store in TrackedFile
            now = datetime.now()
            tracked_file.retry_info = RetryInfo(
                scheduled_at=now,
                retry_at=now + timedelta(seconds=delay_seconds),
                reason=reason,
                retry_type=retry_type
            )
            
            # Schedule the retry task
            retry_task = asyncio.create_task(
                self._execute_retry_task(file_id, delay_seconds)
            )
            self._retry_tasks[file_id] = retry_task
            
            logging.info(f"Scheduled {retry_type} retry for {tracked_file.file_path} in {delay_seconds}s: {reason}")
            return True

    async def cancel_retry(self, file_id: str) -> bool:
        """Cancel any pending retry for a file."""
        async with self._lock:
            return await self._cancel_existing_retry_unlocked(file_id)

    async def _cancel_existing_retry_unlocked(self, file_id: str) -> bool:
        """Cancel existing retry without acquiring lock (internal use)."""
        retry_cancelled = False
        
        # Cancel task
        if file_id in self._retry_tasks:
            task = self._retry_tasks.pop(file_id)
            task.cancel()
            retry_cancelled = True
            
            try:
                # Wait for task to finish with a short timeout
                await asyncio.wait_for(task, timeout=0.1)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                # Expected when task is cancelled or takes too long
                pass
            except Exception as e:
                logging.warning(f"Error while cancelling task for {file_id}: {e}")
        
        # Clear retry info from TrackedFile
        tracked_file = self._files_by_id.get(file_id)
        if tracked_file and tracked_file.retry_info:
            tracked_file.retry_info = None
            retry_cancelled = True
        
        if retry_cancelled:
            logging.debug(f"Cancelled retry for file ID: {file_id}")
        
        return retry_cancelled

    async def _execute_retry_task(self, file_id: str, delay_seconds: int) -> None:
        """Execute the actual retry after delay."""
        try:
            await asyncio.sleep(delay_seconds)
            
            # Check if file still exists and needs retry
            async with self._lock:
                tracked_file = self._files_by_id.get(file_id)
                
                if not tracked_file or not tracked_file.retry_info:
                    logging.debug(f"Retry cancelled - file or retry info missing: {file_id}")
                    return
                
                # Only proceed if file is still waiting for space
                if tracked_file.status != FileStatus.WAITING_FOR_SPACE:
                    logging.debug(f"Retry cancelled - file status changed: {tracked_file.file_path}")
                    return
                
                # Reset file to READY status
                old_status = tracked_file.status
                tracked_file.status = FileStatus.READY
                tracked_file.error_message = None
                tracked_file.retry_info = None  # Clear retry info
                
                logging.info(f"Retry executed for {tracked_file.file_path} - reset to READY")
                
                # Clean up task tracking
                self._retry_tasks.pop(file_id, None)
                
                # Notify subscribers
                await self._notify(
                    FileStateUpdate(
                        file_path=tracked_file.file_path,
                        old_status=old_status,
                        new_status=FileStatus.READY,
                        tracked_file=tracked_file,
                    )
                )
        
        except asyncio.CancelledError:
            # Clean up on cancellation
            async with self._lock:
                tracked_file = self._files_by_id.get(file_id)
                if tracked_file:
                    tracked_file.retry_info = None
                self._retry_tasks.pop(file_id, None)
            raise
        except Exception as e:
            logging.error(f"Error in retry task for file ID {file_id}: {e}")
            # Clean up on error
            async with self._lock:
                tracked_file = self._files_by_id.get(file_id)
                if tracked_file:
                    tracked_file.retry_info = None
                self._retry_tasks.pop(file_id, None)

    async def get_retry_info(self, file_id: str) -> Optional[RetryInfo]:
        """Get retry information for a file."""
        async with self._lock:
            tracked_file = self._files_by_id.get(file_id)
            return tracked_file.retry_info if tracked_file else None

    async def cancel_all_retries(self) -> int:
        """Cancel all pending retries. Returns number of retries cancelled."""
        async with self._lock:
            cancelled_count = 0
            
            # Cancel all retry tasks and clear retry info from files
            files_with_retries = [
                file_id for file_id, tracked_file in self._files_by_id.items()
                if tracked_file.retry_info is not None
            ]
            
            for file_id in files_with_retries:
                if await self._cancel_existing_retry_unlocked(file_id):
                    cancelled_count += 1
            
            logging.info(f"Cancelled {cancelled_count} pending retries")
            return cancelled_count

    async def increment_retry_count(self, file_id: str) -> int:
        """Increment retry count for a file and return new count."""
        async with self._lock:
            tracked_file = self._files_by_id.get(file_id)
            if not tracked_file:
                logging.warning(f"Cannot increment retry count for unknown file ID: {file_id}")
                return 0
            
            tracked_file.retry_count += 1
            logging.debug(f"Incremented retry count for {tracked_file.file_path} to {tracked_file.retry_count}")
            return tracked_file.retry_count
