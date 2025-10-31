from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class CopyResult:
    success: bool
    source_path: Path
    destination_path: Path
    bytes_copied: int
    elapsed_seconds: float
    start_time: datetime
    end_time: datetime
    error_message: Optional[str] = None
    verification_successful: bool = True
    temp_file_used: bool = False
    temp_file_path: Optional[Path] = None

    @property
    def transfer_rate_bytes_per_sec(self) -> float:
        """Calculate transfer rate in bytes per second."""
        if self.elapsed_seconds <= 0:
            return 0.0
        return self.bytes_copied / self.elapsed_seconds

    @property
    def transfer_rate_mb_per_sec(self) -> float:
        """Calculate transfer rate in MB per second."""
        return self.transfer_rate_bytes_per_sec / (1024 * 1024)

    @property
    def size_mb(self) -> float:
        """Get file size in MB."""
        return self.bytes_copied / (1024 * 1024)

    def get_summary(self) -> str:
        """Get a human-readable summary of the copy operation."""
        if self.success:
            return (
                f"Copy successful: {self.source_path.name} "
                f"({self.size_mb:.2f} MB in {self.elapsed_seconds:.2f}s, "
                f"{self.transfer_rate_mb_per_sec:.2f} MB/s)"
            )
        else:
            return (
                f"Copy failed: {self.source_path.name} - "
                f"{self.error_message or 'Unknown error'}"
            )


@dataclass
class CopyProgress:
    """Progress information for an ongoing copy operation."""

    bytes_copied: int
    total_bytes: int
    elapsed_seconds: float
    current_rate_bytes_per_sec: float

    @property
    def progress_percent(self) -> float:
        """Calculate completion percentage (0.0 to 100.0)."""
        if self.total_bytes <= 0:
            return 0.0
        return min(100.0, (self.bytes_copied / self.total_bytes) * 100.0)

    @property
    def progress_percent_int(self) -> int:
        """Get completion percentage as integer (0 to 100)."""
        return int(self.progress_percent)

    @property
    def remaining_bytes(self) -> int:
        """Calculate remaining bytes to copy."""
        return max(0, self.total_bytes - self.bytes_copied)

    @property
    def estimated_remaining_seconds(self) -> float:
        """Estimate remaining time in seconds based on current rate."""
        if self.current_rate_bytes_per_sec <= 0:
            return 0.0
        return self.remaining_bytes / self.current_rate_bytes_per_sec