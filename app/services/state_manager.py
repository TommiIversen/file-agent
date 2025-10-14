import asyncio
import logging
from typing import Dict, List, Optional, Set, Callable, Awaitable
from datetime import datetime

from app.models import TrackedFile, FileStatus, FileStateUpdate


class StateManager:
    """
    Central state management for alle tracked filer.

    Denne klasse er designet som en singleton og håndterer:
    - Tilføjelse og fjernelse af filer
    - Status opdateringer med pub/sub events
    - Thread-safe operationer med asyncio.Lock
    - Cleanup af filer der ikke længere eksisterer
    """

    def __init__(self):
        """Initialize StateManager med tom tilstand."""
        # NEW: UUID-based storage - single source of truth
        self._files_by_id: Dict[str, TrackedFile] = {}  # UUID -> TrackedFile
        self._lock = asyncio.Lock()
        self._subscribers: List[Callable[[FileStateUpdate], Awaitable[None]]] = []

        logging.info("StateManager initialiseret")

    def _get_current_file_for_path(self, file_path: str) -> Optional[TrackedFile]:
        """
        Get the most recent (current) file for a given path.
        
        Returns the newest file entry for this path, prioritizing active statuses.
        """
        candidates = [
            f for f in self._files_by_id.values() 
            if f.file_path == file_path
        ]
        if not candidates:
            return None
        
        # Sort by priority: Active statuses first, then by discovered_at (newest first)
        def sort_key(f: TrackedFile):
            # Active statuses get highest priority (lower number = higher priority)
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
                FileStatus.REMOVED: 14,  # Lowest priority
                FileStatus.SPACE_ERROR: 15,
            }
            
            priority = active_statuses.get(f.status, 99)
            # Use discovered_at as secondary sort (newer = higher priority)
            time_priority = -(f.discovered_at.timestamp() if f.discovered_at else 0)
            return (priority, time_priority)
        
        return min(candidates, key=sort_key)
    
    def _get_all_files_for_path(self, file_path: str) -> List[TrackedFile]:
        """Get ALL files (including history) for a given path."""
        return [
            f for f in self._files_by_id.values() 
            if f.file_path == file_path
        ]

    async def add_file(
        self, file_path: str, file_size: int, last_write_time: Optional[datetime] = None
    ) -> TrackedFile:
        """
        Tilføj en ny fil til tracking systemet.
        
        Automatic history management: If file with same path exists as REMOVED,
        it will be preserved as history and a new entry created.

        Args:
            file_path: Absolut sti til filen
            file_size: Filstørrelse i bytes
            last_write_time: Sidste modificerings tidspunkt

        Returns:
            Det oprettede TrackedFile objekt
        """
        async with self._lock:
            # Check if current file exists
            existing = self._get_current_file_for_path(file_path)
            if existing and existing.status != FileStatus.REMOVED:
                logging.debug(f"Fil allerede tracked: {file_path}")
                return existing

            # Create new file (gets new UUID automatically)
            tracked_file = TrackedFile(
                file_path=file_path,
                file_size=file_size,
                last_write_time=last_write_time,
                status=FileStatus.DISCOVERED,
            )

            # Store by UUID (automatic history preservation)
            self._files_by_id[tracked_file.id] = tracked_file

            if existing and existing.status == FileStatus.REMOVED:
                logging.info(f"File returned after REMOVED - creating new entry: {file_path}")
                logging.info(f"Previous REMOVED entry preserved as history: {existing.id}")
            else:
                logging.info(f"Ny fil tilføjet: {file_path} ({file_size} bytes)")

        # Notify subscribers EFTER lock er frigivet for at undgå deadlock
        await self._notify(
            FileStateUpdate(
                file_path=file_path,
                old_status=None,
                new_status=FileStatus.DISCOVERED,
                tracked_file=tracked_file,
            )
        )

        return tracked_file

    async def update_file_status(
        self, file_path: str, status: FileStatus, **kwargs
    ) -> Optional[TrackedFile]:
        """
        Opdater status og andre attributter for en tracked fil.
        
        Updates the current (most recent) file entry for the given path.

        Args:
            file_path: Sti til filen der skal opdateres
            status: Ny status for filen
            **kwargs: Andre attributter der skal opdateres

        Returns:
            Det opdaterede TrackedFile objekt eller None hvis ikke fundet
        """
        async with self._lock:
            tracked_file = self._get_current_file_for_path(file_path)
            if not tracked_file:
                logging.warning(f"Forsøg på at opdatere ukendt fil: {file_path}")
                return None

            old_status = tracked_file.status

            # Opdater status
            tracked_file.status = status

            # Automatisk sæt is_growing_file flag baseret på status
            if status == FileStatus.READY_TO_START_GROWING:
                tracked_file.is_growing_file = True
            elif status in [FileStatus.READY, FileStatus.COMPLETED]:
                # Reset growing flag for stable files ONLY if not explicitly set
                if "is_growing_file" not in kwargs:
                    tracked_file.is_growing_file = False
            # Preserve is_growing_file for COPYING, IN_QUEUE, etc. (don't reset)

            # Opdater andre attributter
            for key, value in kwargs.items():
                if hasattr(tracked_file, key):
                    setattr(tracked_file, key, value)
                else:
                    logging.warning(f"Ukendt attribut ignored: {key}")

            # Sæt tidsstempler baseret på status
            if status == FileStatus.COPYING and not tracked_file.started_copying_at:
                tracked_file.started_copying_at = datetime.now()
            elif status == FileStatus.COMPLETED and not tracked_file.completed_at:
                tracked_file.completed_at = datetime.now()

            # Only log when status actually changes (not for progress updates)
            if old_status != status:
                logging.info(f"Status opdateret: {file_path} {old_status} -> {status}")
            else:
                # Log progress updates at debug level only
                if "copy_progress" in kwargs:
                    logging.debug(
                        f"Progress opdateret: {file_path} {kwargs['copy_progress']:.1f}%"
                    )
                else:
                    logging.debug(
                        f"Attributes opdateret: {file_path} {list(kwargs.keys())}"
                    )

        # Notify subscribers EFTER lock er frigivet for at undgå deadlock
        await self._notify(
            FileStateUpdate(
                file_path=file_path,
                old_status=old_status,
                new_status=status,
                tracked_file=tracked_file,
            )
        )

        return tracked_file

    async def remove_file(self, file_path: str) -> bool:
        """
        Remove the current file entry for the given path.
        
        Note: This only removes the current entry, history is preserved.
        """
        async with self._lock:
            current_file = self._get_current_file_for_path(file_path)
            if not current_file:
                return False

            self._files_by_id.pop(current_file.id, None)

            logging.info(f"Fil fjernet fra tracking: {file_path} (ID: {current_file.id})")

            # Note: Vi notificerer ikke subscribers for remove events
            # da det typisk sker ved cleanup og ikke er interessant for UI

            return True

    async def get_file(self, file_path: str) -> Optional[TrackedFile]:
        """
        Get the current (most recent/active) file for the given path.
        
        This maintains backward compatibility while supporting automatic history.
        """
        async with self._lock:
            return self._get_current_file_for_path(file_path)

    async def get_all_files(self) -> List[TrackedFile]:
        """
        Get all files - returns current entries only, not historical ones.
        
        For each file_path, only the most recent/active entry is returned.
        Excludes REMOVED files as they are considered historical.
        """
        async with self._lock:
            # Group by file_path and return only current entries
            current_files = {}
            for tracked_file in self._files_by_id.values():
                # Skip REMOVED files - they're historical
                if tracked_file.status == FileStatus.REMOVED:
                    continue
                    
                current = current_files.get(tracked_file.file_path)
                if not current or self._is_more_current(tracked_file, current):
                    current_files[tracked_file.file_path] = tracked_file
            
            return list(current_files.values())
    
    def _is_more_current(self, file1: TrackedFile, file2: TrackedFile) -> bool:
        """Check if file1 is more current than file2 (for same file_path)."""
        # Same logic as _get_current_file_for_path sort key
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
            
        # Same priority - use discovery time
        time1 = file1.discovered_at.timestamp() if file1.discovered_at else 0
        time2 = file2.discovered_at.timestamp() if file2.discovered_at else 0
        return time1 > time2

    async def get_files_by_status(self, status: FileStatus) -> List[TrackedFile]:
        """
        Get files by status - returns current entries only.
        
        For each file_path, only the most recent entry is considered.
        """
        async with self._lock:
            # Group by file_path and return only current entries with matching status
            current_files = {}
            for tracked_file in self._files_by_id.values():
                if tracked_file.status == status:
                    current = current_files.get(tracked_file.file_path)
                    if not current or self._is_more_current(tracked_file, current):
                        current_files[tracked_file.file_path] = tracked_file
            
            return list(current_files.values())


    async def cleanup_missing_files(self, existing_paths: Set[str]) -> int:
        """
        Mark missing files as REMOVED (preserves in history).

        VIGTIGT: COMPLETED filer bevares i memory selvom source filen er slettet.
        Andre filer markeres som REMOVED for history tracking.

        Args:
            existing_paths: Set af stier til filer der stadig eksisterer

        Returns:
            Antal filer der blev markeret som REMOVED
        """
        removed_count = 0

        async with self._lock:
            # Get current files for each path
            current_files = {}
            for tracked_file in self._files_by_id.values():
                current = current_files.get(tracked_file.file_path)
                if not current or self._is_more_current(tracked_file, current):
                    current_files[tracked_file.file_path] = tracked_file

            # Process missing files
            for file_path, tracked_file in current_files.items():
                if file_path not in existing_paths:
                    # Bevar COMPLETED filer i memory
                    if tracked_file.status == FileStatus.COMPLETED:
                        logging.debug(f"Bevarer completed fil i memory: {file_path}")
                        continue

                    # Bevar filer der er under processing (COPYING, IN_QUEUE, etc.)
                    if tracked_file.status in [
                        FileStatus.COPYING,
                        FileStatus.IN_QUEUE,
                        FileStatus.GROWING_COPY,
                    ]:
                        logging.debug(
                            f"Bevarer fil under processing: {file_path} (status: {tracked_file.status})"
                        )
                        continue

                    # Mark as REMOVED instead of deleting (preserves history)
                    if tracked_file.status != FileStatus.REMOVED:
                        old_status = tracked_file.status
                        tracked_file.status = FileStatus.REMOVED
                        removed_count += 1
                        logging.info(f"Marked missing file as REMOVED: {file_path} (was {old_status})")

        if removed_count > 0:
            logging.info(
                f"Cleanup: Markerede {removed_count} manglende filer som REMOVED"
            )

        return removed_count

    async def cleanup_old_completed_files(
        self, max_age_hours: int, max_count: int
    ) -> int:
        """
        Fjern gamle COMPLETED filer fra memory for at holde memory usage nede.

        Args:
            max_age_hours: Max alder i timer for completed files
            max_count: Max antal completed files at holde i memory

        Returns:
            Antal completed files der blev fjernet
        """
        from datetime import timedelta

        removed_count = 0
        now = datetime.now()
        cutoff_time = now - timedelta(hours=max_age_hours)

        async with self._lock:
            # Find completed files der skal fjernes (current entries only)
            current_files = {}
            for tracked_file in self._files_by_id.values():
                if tracked_file.status == FileStatus.COMPLETED:
                    current = current_files.get(tracked_file.file_path)
                    if not current or self._is_more_current(tracked_file, current):
                        current_files[tracked_file.file_path] = tracked_file
            
            completed_files = [
                (file.file_path, file)
                for file in current_files.values()
            ]

            # Sort by completion time (newest first)
            completed_files.sort(
                key=lambda x: x[1].completed_at or datetime.min, reverse=True
            )

            to_remove = []

            # Remove files older than cutoff_time
            for file_path, tracked_file in completed_files:
                if (
                    tracked_file.completed_at
                    and tracked_file.completed_at < cutoff_time
                ):
                    to_remove.append(file_path)

            # If still too many, remove oldest ones to stay under max_count
            if len(completed_files) - len(to_remove) > max_count:
                remaining_files = [
                    (path, file)
                    for path, file in completed_files
                    if path not in to_remove
                ]
                excess_count = len(remaining_files) - max_count

                # Remove oldest files beyond max_count
                for i in range(excess_count):
                    file_path, _ = remaining_files[-(i + 1)]  # Start from oldest
                    to_remove.append(file_path)

            # Remove the files by finding their current IDs
            for file_path in to_remove:
                current_file = self._get_current_file_for_path(file_path)
                if current_file:
                    self._files_by_id.pop(current_file.id, None)
                    removed_count += 1
                    logging.debug(f"Cleanup: Fjernet gammel completed fil: {file_path}")

        if removed_count > 0:
            logging.info(
                f"Cleanup: Fjernede {removed_count} gamle completed filer fra memory"
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

    # NEW: History and ID-based APIs for future migration
    async def get_file_history(self, file_path: str) -> List[TrackedFile]:
        """
        Get ALL file entries (current + historical) for a given path.
        
        Returns list sorted by discovery time (newest first).
        """
        async with self._lock:
            history = self._get_all_files_for_path(file_path)
            # Sort by discovery time (newest first)
            return sorted(
                history, 
                key=lambda f: f.discovered_at or datetime.min, 
                reverse=True
            )
    
    async def get_file_by_id(self, file_id: str) -> Optional[TrackedFile]:
        """
        Get a specific file by its UUID.
        
        Useful for direct access to historical entries.
        """
        async with self._lock:
            return self._files_by_id.get(file_id)
    
    async def update_file_status_by_id(
        self, file_id: str, status: FileStatus, **kwargs
    ) -> Optional[TrackedFile]:
        """
        Update a specific file by UUID (for future migration).
        
        Allows precise control over which file entry to update.
        """
        async with self._lock:
            tracked_file = self._files_by_id.get(file_id)
            if not tracked_file:
                logging.warning(f"Forsøg på at opdatere ukendt fil ID: {file_id}")
                return None

            old_status = tracked_file.status
            tracked_file.status = status

            # Apply same update logic as path-based method
            if status == FileStatus.READY_TO_START_GROWING:
                tracked_file.is_growing_file = True
            elif status in [FileStatus.READY, FileStatus.COMPLETED]:
                if "is_growing_file" not in kwargs:
                    tracked_file.is_growing_file = False

            # Opdater andre attributter
            for key, value in kwargs.items():
                if hasattr(tracked_file, key):
                    setattr(tracked_file, key, value)
                else:
                    logging.warning(f"Ukendt attribut ignored: {key}")

            # Sæt tidsstempler baseret på status
            if status == FileStatus.COPYING and not tracked_file.started_copying_at:
                tracked_file.started_copying_at = datetime.now()
            elif status == FileStatus.COMPLETED and not tracked_file.completed_at:
                tracked_file.completed_at = datetime.now()

            if old_status != status:
                logging.info(f"Status opdateret (ID): {tracked_file.file_path} {old_status} -> {status}")

        # Notify subscribers
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

        # Kald alle subscribers asynckront
        tasks = []
        for callback in self._subscribers:
            try:
                task = asyncio.create_task(callback(update))
                tasks.append(task)
            except Exception as e:
                logging.error(f"Fejl ved oprettelse af subscriber task: {e}")

        # Vent på alle callbacks, men log fejl hvis nogen fejler
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logging.error(f"Subscriber {i} fejlede: {result}")

    async def get_statistics(self) -> Dict:
        async with self._lock:
            # Get current files for statistics (avoid circular call)
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

            # Beregn total filstørrelse
            total_size = sum(f.file_size for f in current_files_list)

            # Find aktive kopiering
            copying_files = [
                f for f in current_files_list if f.status == FileStatus.COPYING
            ]

            # Find growing files
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
        """Get all files that are currently active in copy pipeline (current entries only).""" 
        async with self._lock:
            # Get current files directly
            current_files = {}
            for tracked_file in self._files_by_id.values():
                if tracked_file.status in [FileStatus.IN_QUEUE, FileStatus.COPYING, FileStatus.GROWING_COPY]:
                    current = current_files.get(tracked_file.file_path)
                    if not current or self._is_more_current(tracked_file, current):
                        current_files[tracked_file.file_path] = tracked_file
            
            return list(current_files.values())

    async def get_paused_files(self) -> List[TrackedFile]:
        """Get all paused files (current entries only)."""
        async with self._lock:
            # Get current paused files directly  
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
