"""
Shared models for job processing services.

Contains data classes and models that are shared between job processing services
to avoid circular import dependencies.
"""

from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING
from pathlib import Path

if TYPE_CHECKING:
    from app.models import TrackedFile, FileStatus


@dataclass
class ProcessResult:
    """
    Result of a job processing operation.
    
    Provides information about job processing outcome and any errors.
    """
    success: bool
    file_path: str
    error_message: Optional[str] = None
    retry_scheduled: bool = False
    space_shortage: bool = False
    should_retry: bool = False  # Indicates error should be retried (for pause/resume)
    
    def get_summary(self) -> str:
        """Get a human-readable summary of the processing result."""
        if self.success:
            return f"Job processed successfully: {Path(self.file_path).name}"
        elif self.space_shortage:
            return f"Space shortage, retry scheduled: {Path(self.file_path).name}"
        else:
            return f"Job failed: {Path(self.file_path).name} - {self.error_message or 'Unknown error'}"


@dataclass
class PreparedFile:
    """
    Information about a file prepared for copying.
    
    Contains validated file information and copy strategy.
    """
    tracked_file: 'TrackedFile'  # Forward reference to avoid circular import
    strategy_name: str
    initial_status: 'FileStatus'  # Forward reference to avoid circular import
    destination_path: Path
