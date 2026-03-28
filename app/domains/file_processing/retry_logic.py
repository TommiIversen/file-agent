"""
Pure logic for retry decisions and network recovery — no I/O, no mocks needed.
Extracted from SpaceRetryManager and JobQueue to enable zero-mock testing.
"""

from app.models import TrackedFile, FileStatus


class RetryLimitChecker:
    """Pure logic: should we give up retrying?"""

    @staticmethod
    def should_give_up(
        current_retry_count: int, max_retries: int
    ) -> tuple[bool, str]:
        if current_retry_count >= max_retries:
            return True, f"Exceeded max retries ({max_retries})"
        return False, ""


class RetryDecision:
    """Pure logic: should a scheduled retry proceed?"""

    @staticmethod
    def should_retry_proceed(
        tracked_file: TrackedFile | None,
        expected_status: FileStatus = FileStatus.WAITING_FOR_SPACE,
    ) -> tuple[bool, str]:
        if tracked_file is None:
            return False, "File not found"
        if tracked_file.retry_info is None:
            return False, "Retry info missing"
        if tracked_file.status != expected_status:
            return False, f"Status changed to {tracked_file.status.value}"
        return True, ""


class NetworkRecoveryDecision:
    """Pure logic: determine status after network recovery."""

    @staticmethod
    def determine_recovery_status(
        tracked_file: TrackedFile,
    ) -> tuple[FileStatus, str]:
        if tracked_file.growth_rate_mbps and tracked_file.growth_rate_mbps > 0:
            return (
                FileStatus.READY_TO_START_GROWING,
                "Was growing file — resume growing copy",
            )
        return FileStatus.DISCOVERED, "Re-evaluate for copying"
