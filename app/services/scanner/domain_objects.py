# Domain objects to eliminate primitive obsession and data clumps
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import os
import aiofiles.os


@dataclass(frozen=True)
class FilePath:
    """Domain object representing a file path with its operations."""

    path: str

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def extension(self) -> str:
        return Path(self.path).suffix.lower()

    async def exists(self) -> bool:
        return await aiofiles.os.path.exists(self.path)

    async def is_directory(self) -> bool:
        return await aiofiles.os.path.isdir(self.path)

    def is_mxf_file(self) -> bool:
        return self.extension == ".mxf"

    def should_ignore(self) -> bool:
        """Check if file should be ignored (test files, etc.)"""
        return "test_file" in self.name.lower() or self.name.startswith(".")

    def __hash__(self) -> int:
        """Make FilePath hashable so it can be stored in sets."""
        return hash(self.path)

    def __eq__(self, other) -> bool:
        """Define equality based on path."""
        if not isinstance(other, FilePath):
            return False
        return self.path == other.path


@dataclass
class FileMetadata:
    """Domain object encapsulating file metadata and operations."""

    path: FilePath
    size: int
    last_write_time: datetime

    @classmethod
    async def from_path(cls, file_path: str) -> Optional["FileMetadata"]:
        """Create FileMetadata from a file path."""
        try:
            path_obj = FilePath(file_path)
            if not await path_obj.exists():
                return None

            stat_result = await aiofiles.os.stat(file_path)
            return cls(
                path=path_obj,
                size=stat_result.st_size,
                last_write_time=datetime.fromtimestamp(stat_result.st_mtime),
            )
        except (OSError, IOError):
            return None

    def is_stable(self, stable_duration: timedelta, last_seen: datetime) -> bool:
        """Check if file has been stable for the required duration."""
        time_since_last_change = datetime.now() - last_seen
        return time_since_last_change >= stable_duration

    def is_empty(self) -> bool:
        return self.size == 0

    def size_mb(self) -> float:
        return self.size / (1024 * 1024)


@dataclass
class ScanConfiguration:
    """Configuration object to eliminate long parameter lists."""

    source_directory: str
    polling_interval_seconds: int
    file_stable_time_seconds: int
    enable_growing_file_support: bool
    growing_file_min_size_mb: int
    keep_files_hours: int  # Renamed: now applies to ALL file types, not just completed
    # Add missing growing file settings
    growing_file_poll_interval_seconds: int = 5
    growing_file_safety_margin_mb: int = 50
    growing_file_growth_timeout_seconds: int = 300
    growing_file_chunk_size_kb: int = 2048
