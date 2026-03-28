"""
Pure logic for file growth status analysis — no I/O, no mocks needed.
Extracted from GrowingFileDetector to enable zero-mock testing.
"""

from datetime import datetime

from app.models import FileStatus


class GrowthStatusAnalyzer:
    """Determine file growth status — pure logic, no dependencies."""

    @staticmethod
    def determine_status(
        current_size: int,
        previous_size: int,
        growth_stable_since: datetime | None,
        current_time: datetime,
        min_size_bytes: int,
        stability_timeout_seconds: float,
    ) -> FileStatus:
        """Pure function: return recommended FileStatus based on growth data."""
        if current_size != previous_size:
            # File is growing
            if current_size >= min_size_bytes:
                return FileStatus.READY_TO_START_GROWING
            return FileStatus.GROWING

        # File is not growing
        if growth_stable_since is None:
            # Just stopped growing — caller should start stability timer
            return FileStatus.GROWING

        stable_seconds = (current_time - growth_stable_since).total_seconds()
        if stable_seconds >= stability_timeout_seconds:
            return FileStatus.READY

        # Not stable long enough yet
        return FileStatus.GROWING

    @staticmethod
    def calculate_growth_rate_mbps(
        current_size: int,
        first_seen_size: int,
        elapsed_seconds: float,
    ) -> float:
        """Pure function: calculate growth rate in MB/s."""
        if elapsed_seconds <= 0 or first_seen_size <= 0:
            return 0.0
        size_diff_mb = (current_size - first_seen_size) / (1024 * 1024)
        return size_diff_mb / elapsed_seconds

    @staticmethod
    def determine_stability_timestamp(
        current_size: int,
        previous_size: int,
        growth_stable_since: datetime | None,
        current_time: datetime,
    ) -> datetime | None:
        """Pure function: determine when the file became stable."""
        if current_size > previous_size:
            return None  # Still growing
        if growth_stable_since is None:
            return current_time  # Just stopped
        return growth_stable_since  # Already stable
