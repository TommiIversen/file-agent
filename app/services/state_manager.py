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


    async def get_file_by_id(self, file_id: str) -> Optional[TrackedFile]:
        async with self._lock:
            result = await self._file_repository.get_by_id(file_id)
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
