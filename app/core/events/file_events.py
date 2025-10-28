"""
Domain events specific to file operations.
"""

from dataclasses import dataclass
from typing import Optional

from app.core.events.domain_event import DomainEvent
from app.models import FileStatus


@dataclass(frozen=True)
class FileDiscoveredEvent(DomainEvent):
    """Event published when a new file is discovered by the scanner."""

    file_path: str
    file_size: int
    last_write_time: float


@dataclass(frozen=True)
class FileStatusChangedEvent(DomainEvent):
    """Event published when a file's status changes."""

    file_id: str
    file_path: str
    old_status: Optional[FileStatus]
    new_status: FileStatus


@dataclass(frozen=True)
class FileReadyEvent(DomainEvent):
    """Event published when a file becomes stable and is ready for processing."""

    file_id: str
    file_path: str


@dataclass(frozen=True)
class FileCopyStartedEvent(DomainEvent):
    """Event published when a file copy operation begins."""

    file_id: str
    file_path: str
    destination_path: str


@dataclass(frozen=True)
class FileCopyCompletedEvent(DomainEvent):
    """Event published when a file copy operation completes successfully."""

    file_id: str
    file_path: str
    destination_path: str
    bytes_copied: int


@dataclass(frozen=True)
class FileCopyFailedEvent(DomainEvent):
    """Event published when a file copy operation fails."""

    file_id: str
    file_path: str
    error_message: str


@dataclass(frozen=True)
class FileCopyProgressEvent(DomainEvent):
    """Event published periodically during a file copy operation."""

    file_id: str
    bytes_copied: int
    total_bytes: int
    copy_speed_mbps: float


@dataclass(frozen=True)
class NetworkFailureDetectedEvent(DomainEvent):
    """Event published when a network failure is detected by any part of the system."""

    detected_by: str
    error_message: str
