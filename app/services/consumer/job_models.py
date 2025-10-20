"""
Job Models for Consumer - typed data structures for job queue system.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.models import TrackedFile, FileStatus


@dataclass
class QueueJob:
    """Typed job object for the job queue system with UUID-based architecture."""

    tracked_file: TrackedFile
    added_to_queue_at: datetime
    retry_count: int = 0
    last_retry_at: Optional[datetime] = None
    requeued_at: Optional[datetime] = None
    last_error_message: Optional[str] = None

    @property
    def file_id(self) -> str:
        """Get the UUID of the tracked file."""
        return self.tracked_file.id

    @property
    def file_path(self) -> str:
        """Get the file path for logging and compatibility."""
        return self.tracked_file.file_path

    @property
    def file_size(self) -> int:
        """Get the file size for progress tracking."""
        return self.tracked_file.file_size

    def mark_retry(self, error_message: str) -> None:
        """Mark this job for retry with error information."""
        self.retry_count += 1
        self.last_retry_at = datetime.now()
        self.last_error_message = error_message

    def mark_requeued(self) -> None:
        """Mark this job as requeued."""
        self.requeued_at = datetime.now()

    def __str__(self) -> str:
        return (
            f"QueueJob(id={self.file_id[:8]}, "
            f"path={self.file_path}, "
            f"size={self.file_size:,}, "
            f"retries={self.retry_count})"
        )


@dataclass
class JobResult:
    """
    Result object for completed job processing.

    Provides structured information about job completion
    for metrics and error handling.
    """

    job: QueueJob
    success: bool
    processing_time_seconds: float
    error_message: Optional[str] = None

    @property
    def file_id(self) -> str:
        """Get the file UUID for logging."""
        return self.job.file_id

    @property
    def file_path(self) -> str:
        """Get the file path for logging."""
        return self.job.file_path

    def __str__(self) -> str:
        """Human-readable representation for logging."""
        status = "SUCCESS" if self.success else "FAILED"
        return (
            f"JobResult({status}, "
            f"file={self.job.file_path}, "
            f"time={self.processing_time_seconds:.2f}s)"
        )


@dataclass
class ProcessResult:
    """
    Result object for job processor workflow.

    Indicates the outcome of processing a job through the entire workflow.
    Used by JobProcessor to communicate results back to the consumer.
    """

    success: bool
    file_path: str
    error_message: Optional[str] = None
    should_retry: bool = False
    retry_scheduled: bool = False
    space_shortage: bool = False

    def __str__(self) -> str:
        """Human-readable representation for logging."""
        status = "SUCCESS" if self.success else "FAILED"
        extras = []
        if self.should_retry:
            extras.append("retry=true")
        if self.retry_scheduled:
            extras.append("scheduled=true")
        if self.space_shortage:
            extras.append("space_shortage=true")

        extra_str = f" ({', '.join(extras)})" if extras else ""
        return f"ProcessResult({status}, {self.file_path}{extra_str})"


@dataclass
class PreparedFile:
    """
    File preparation result from JobFilePreparationService.

    Contains all information needed to execute a copy operation
    including strategy selection and destination path calculation.
    """

    tracked_file: TrackedFile
    strategy_name: str
    initial_status: FileStatus
    destination_path: Path

    @property
    def file_id(self) -> str:
        """Get the UUID of the tracked file."""
        return self.tracked_file.id

    @property
    def file_path(self) -> str:
        """Get the source file path."""
        return self.tracked_file.file_path

    @property
    def file_size(self) -> int:
        """Get the file size."""
        return self.tracked_file.file_size

    def __str__(self) -> str:
        """Human-readable representation for logging."""
        return (
            f"PreparedFile(id={self.file_id[:8]}, "
            f"strategy={self.strategy_name}, "
            f"dest={self.destination_path.name})"
        )
