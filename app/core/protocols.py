"""
Repository protocols for dependency inversion.

Defines the interface that any FileRepository implementation must satisfy.
Both the in-memory FileRepository and SqliteFileRepository implement this protocol.
"""

from datetime import datetime
from typing import List, Optional, Protocol, Set, runtime_checkable

from app.models import FileStatus, TrackedFile


@runtime_checkable
class FileRepositoryProtocol(Protocol):
    """Protocol defining the FileRepository interface."""

    async def get_by_id(self, file_id: str) -> Optional[TrackedFile]: ...
    async def get_all(self) -> List[TrackedFile]: ...
    async def add(self, tracked_file: TrackedFile) -> None: ...
    async def update(self, tracked_file: TrackedFile) -> None: ...
    async def remove(self, file_id: str) -> bool: ...
    async def count(self) -> int: ...
    async def prune_terminal_files(
        self, terminal_states: Set[FileStatus], cutoff_date: datetime
    ) -> int: ...
