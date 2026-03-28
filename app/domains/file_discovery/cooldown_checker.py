"""
Pure logic for cooldown checking — no I/O, no mocks needed.
Extracted from FileDiscoverySlice to enable zero-mock testing.
"""

from datetime import datetime, timedelta

from app.models import TrackedFile, FileStatus


class CooldownChecker:
    """Cooldown logic for space errors — pure logic, no dependencies."""

    @staticmethod
    def is_in_cooldown(
        error_timestamp: datetime,
        cooldown_minutes: int,
        current_time: datetime,
    ) -> tuple[bool, float]:
        """Return (is_in_cooldown, minutes_remaining)."""
        cooldown = timedelta(minutes=cooldown_minutes)
        elapsed = current_time - error_timestamp
        in_cooldown = elapsed < cooldown
        remaining = max(0.0, (cooldown - elapsed).total_seconds() / 60)
        return in_cooldown, remaining

    @staticmethod
    def should_skip_space_error(
        tracked_file: TrackedFile,
        cooldown_minutes: int,
        current_time: datetime,
    ) -> tuple[bool, str]:
        """Return (should_skip, reason)."""
        if tracked_file.status != FileStatus.SPACE_ERROR:
            return False, ""
        if not tracked_file.space_error_at:
            return False, ""
        in_cd, remaining = CooldownChecker.is_in_cooldown(
            tracked_file.space_error_at, cooldown_minutes, current_time
        )
        if in_cd:
            return True, f"Space error cooldown: {remaining:.1f} min remaining"
        return False, ""
