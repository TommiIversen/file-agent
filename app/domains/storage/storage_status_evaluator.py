"""
Pure logic for storage status evaluation — no I/O, no mocks needed.
Extracted from StorageChecker to enable zero-mock testing.
"""

from app.models import StorageStatus


class StorageStatusEvaluator:
    """Evaluate disk status — pure logic, no dependencies."""

    @staticmethod
    def evaluate(
        free_gb: float,
        warning_threshold_gb: float,
        critical_threshold_gb: float,
        is_accessible: bool,
        has_write_access: bool,
    ) -> StorageStatus:
        if not is_accessible:
            return StorageStatus.ERROR
        if not has_write_access:
            return StorageStatus.CRITICAL
        if free_gb < critical_threshold_gb:
            return StorageStatus.CRITICAL
        if free_gb < warning_threshold_gb:
            return StorageStatus.WARNING
        return StorageStatus.OK

    @staticmethod
    def build_error_message(
        is_accessible: bool,
        has_write_access: bool,
        free_gb: float,
        critical_threshold_gb: float,
    ) -> str | None:
        if not is_accessible:
            return "Path is not accessible"
        if not has_write_access:
            return "No write access"
        if free_gb < critical_threshold_gb:
            return f"Critical: only {free_gb:.1f} GB free"
        return None
