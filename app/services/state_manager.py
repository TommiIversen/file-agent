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
        self._files: Dict[str, TrackedFile] = {}
        self._lock = asyncio.Lock()
        self._subscribers: List[Callable[[FileStateUpdate], Awaitable[None]]] = []

        logging.info("StateManager initialiseret")

    async def add_file(
        self, file_path: str, file_size: int, last_write_time: Optional[datetime] = None
    ) -> TrackedFile:
        """
        Tilføj en ny fil til tracking systemet.

        Args:
            file_path: Absolut sti til filen
            file_size: Filstørrelse i bytes
            last_write_time: Sidste modificerings tidspunkt

        Returns:
            Det oprettede TrackedFile objekt
        """
        async with self._lock:
            if file_path in self._files:
                logging.debug(f"Fil allerede tracked: {file_path}")
                return self._files[file_path]

            tracked_file = TrackedFile(
                file_path=file_path,
                file_size=file_size,
                last_write_time=last_write_time,
                status=FileStatus.DISCOVERED,
            )

            self._files[file_path] = tracked_file

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

        Args:
            file_path: Sti til filen der skal opdateres
            status: Ny status for filen
            **kwargs: Andre attributter der skal opdateres

        Returns:
            Det opdaterede TrackedFile objekt eller None hvis ikke fundet
        """
        async with self._lock:
            if file_path not in self._files:
                logging.warning(f"Forsøg på at opdatere ukendt fil: {file_path}")
                return None

            tracked_file = self._files[file_path]
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
        async with self._lock:
            if file_path not in self._files:
                return False

            self._files.pop(file_path)

            logging.info(f"Fil fjernet fra tracking: {file_path}")

            # Note: Vi notificerer ikke subscribers for remove events
            # da det typisk sker ved cleanup og ikke er interessant for UI

            return True

    async def get_file(self, file_path: str) -> Optional[TrackedFile]:
        async with self._lock:
            return self._files.get(file_path)

    async def get_all_files(self) -> List[TrackedFile]:
        async with self._lock:
            return list(self._files.values())

    async def get_files_by_status(self, status: FileStatus) -> List[TrackedFile]:
        async with self._lock:
            return [f for f in self._files.values() if f.status == status]


    async def cleanup_missing_files(self, existing_paths: Set[str]) -> int:
        """
        Fjern tracked filer som ikke længere eksisterer på filsystemet.

        VIGTIGT: COMPLETED filer bevares i memory selvom source filen er slettet.
        Dette sikrer at UI kan vise completed files efter page refresh.

        Args:
            existing_paths: Set af stier til filer der stadig eksisterer

        Returns:
            Antal filer der blev fjernet
        """
        removed_count = 0

        async with self._lock:
            # Find filer der skal fjernes
            to_remove = []
            for file_path, tracked_file in self._files.items():
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

                    # Alle andre statuses fjernes når source fil ikke eksisterer
                    to_remove.append(file_path)

            # Fjern dem
            for file_path in to_remove:
                self._files.pop(file_path, None)
                removed_count += 1
                logging.debug(f"Cleanup: Fjernet {file_path}")

        if removed_count > 0:
            logging.info(
                f"Cleanup: Fjernede {removed_count} filer der ikke længere eksisterer"
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
            # Find completed files der skal fjernes
            completed_files = [
                (path, file)
                for path, file in self._files.items()
                if file.status == FileStatus.COMPLETED
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

            # Remove the files
            for file_path in to_remove:
                self._files.pop(file_path, None)
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
            total_files = len(self._files)
            status_counts = {}

            for status in FileStatus:
                status_counts[status.value] = len(
                    [f for f in self._files.values() if f.status == status]
                )

            # Beregn total filstørrelse
            total_size = sum(f.file_size for f in self._files.values())

            # Find aktive kopiering
            copying_files = [
                f for f in self._files.values() if f.status == FileStatus.COPYING
            ]

            # Find growing files
            growing_files = [
                f
                for f in self._files.values()
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
            return [
                tracked_file
                for tracked_file in self._files.values()
                if tracked_file.status
                in [FileStatus.IN_QUEUE, FileStatus.COPYING, FileStatus.GROWING_COPY]
            ]

    async def get_paused_files(self) -> List[TrackedFile]:
        async with self._lock:
            return [
                tracked_file
                for tracked_file in self._files.values()
                if tracked_file.status
                in [
                    FileStatus.PAUSED_IN_QUEUE,
                    FileStatus.PAUSED_COPYING,
                    FileStatus.PAUSED_GROWING_COPY,
                ]
            ]
