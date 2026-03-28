"""
Pure logic for file selection and prioritization — no I/O, no mocks needed.
Extracted from FileDiscoverySlice to enable zero-mock testing.
"""

from app.models import TrackedFile, FileStatus


class FileSelectionLogic:
    """Sort and select files by priority — pure logic, no dependencies."""

    ACTIVE_STATUSES = {
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

    ACTIVE_PRIORITIES = {
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

    ALL_PRIORITIES = {
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
        FileStatus.COMPLETED_DELETE_FAILED: 11,
        FileStatus.FAILED: 12,
        FileStatus.REMOVED: 13,
        FileStatus.SPACE_ERROR: 14,
    }

    @staticmethod
    def active_sort_key(file: TrackedFile) -> tuple:
        """Sort key for active files: lowest priority number + newest time first."""
        priority = FileSelectionLogic.ACTIVE_PRIORITIES.get(file.status, 99)
        time_val = -(file.discovered_at.timestamp() if file.discovered_at else 0)
        return (priority, time_val)

    @staticmethod
    def all_sort_key(file: TrackedFile) -> tuple:
        """Sort key for all files (including terminal): lowest priority + newest first."""
        priority = FileSelectionLogic.ALL_PRIORITIES.get(file.status, 99)
        time_val = -(file.discovered_at.timestamp() if file.discovered_at else 0)
        return (priority, time_val)

    @staticmethod
    def select_active_for_path(
        all_files: list[TrackedFile], file_path: str
    ) -> TrackedFile | None:
        """Select the highest-priority active file for a given path."""
        candidates = [
            f for f in all_files
            if f.file_path == file_path and f.status in FileSelectionLogic.ACTIVE_STATUSES
        ]
        return min(candidates, key=FileSelectionLogic.active_sort_key) if candidates else None

    @staticmethod
    def select_current_for_path(
        all_files: list[TrackedFile], file_path: str
    ) -> TrackedFile | None:
        """Select the highest-priority file for a path, including terminal states."""
        candidates = [f for f in all_files if f.file_path == file_path]
        return min(candidates, key=FileSelectionLogic.all_sort_key) if candidates else None

    @staticmethod
    def is_more_current(file_a: TrackedFile, file_b: TrackedFile) -> bool:
        """Return True if file_a is more current (higher priority) than file_b."""
        return FileSelectionLogic.all_sort_key(file_a) < FileSelectionLogic.all_sort_key(file_b)

    @staticmethod
    def deduplicate_by_path(
        all_files: list[TrackedFile],
    ) -> dict[str, TrackedFile]:
        """Return the most current file per path."""
        result: dict[str, TrackedFile] = {}
        for f in all_files:
            current = result.get(f.file_path)
            if not current or FileSelectionLogic.is_more_current(f, current):
                result[f.file_path] = f
        return result
