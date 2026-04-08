"""Tests for retry_logic functions — 0 mocks, pure logic."""

from app.domains.file_processing.retry_logic import (
    should_give_up,
    should_retry_proceed,
    determine_recovery_status,
)
from app.models import FileStatus, TrackedFile, RetryInfo
from datetime import datetime


def _make_file(
    status: FileStatus = FileStatus.WAITING_FOR_SPACE,
    growth_rate_mbps: float = 0.0,
    retry_info: RetryInfo | None = None,
) -> TrackedFile:
    return TrackedFile(
        file_path="/test/file.mxf",
        status=status,
        growth_rate_mbps=growth_rate_mbps,
        retry_info=retry_info,
    )


def _make_retry_info() -> RetryInfo:
    now = datetime(2025, 1, 1)
    return RetryInfo(
        scheduled_at=now,
        retry_at=now,
        reason="test",
        retry_type="space",
    )


class TestShouldGiveUp:
    def test_should_give_up_at_max(self):
        give_up, msg = should_give_up(5, 5)
        assert give_up is True
        assert "5" in msg

    def test_should_give_up_above_max(self):
        give_up, _ = should_give_up(10, 5)
        assert give_up is True

    def test_should_not_give_up_below_max(self):
        give_up, msg = should_give_up(3, 5)
        assert give_up is False
        assert msg == ""

    def test_should_not_give_up_at_zero(self):
        give_up, _ = should_give_up(0, 5)
        assert give_up is False

    def test_zero_max_always_gives_up(self):
        give_up, _ = should_give_up(0, 0)
        assert give_up is True


class TestShouldRetryProceed:
    def test_proceed_correct_status(self):
        f = _make_file(
            status=FileStatus.WAITING_FOR_SPACE,
            retry_info=_make_retry_info(),
        )
        proceed, _ = should_retry_proceed(f)
        assert proceed is True

    def test_no_proceed_file_none(self):
        proceed, reason = should_retry_proceed(None)
        assert proceed is False
        assert "not found" in reason.lower()

    def test_no_proceed_wrong_status(self):
        f = _make_file(
            status=FileStatus.COPYING,
            retry_info=_make_retry_info(),
        )
        proceed, reason = should_retry_proceed(f)
        assert proceed is False
        assert "Copying" in reason

    def test_no_proceed_retry_info_missing(self):
        f = _make_file(
            status=FileStatus.WAITING_FOR_SPACE,
            retry_info=None,
        )
        proceed, reason = should_retry_proceed(f)
        assert proceed is False
        assert "missing" in reason.lower()

    def test_custom_expected_status(self):
        f = _make_file(
            status=FileStatus.WAITING_FOR_NETWORK,
            retry_info=_make_retry_info(),
        )
        proceed, _ = should_retry_proceed(
            f, expected_status=FileStatus.WAITING_FOR_NETWORK
        )
        assert proceed is True


class TestDetermineRecoveryStatus:
    def test_growing_file_recovers_to_ready_to_start(self):
        f = _make_file(growth_rate_mbps=5.0)
        status, msg = determine_recovery_status(f)
        assert status == FileStatus.READY_TO_START_GROWING
        assert "growing" in msg.lower()

    def test_static_file_recovers_to_discovered(self):
        f = _make_file(growth_rate_mbps=0.0)
        status, msg = determine_recovery_status(f)
        assert status == FileStatus.DISCOVERED

    def test_zero_growth_rate_is_static(self):
        f = _make_file(growth_rate_mbps=0.0)
        status, _ = determine_recovery_status(f)
        assert status == FileStatus.DISCOVERED

    def test_tiny_positive_growth_is_growing(self):
        f = _make_file(growth_rate_mbps=0.001)
        status, _ = determine_recovery_status(f)
        assert status == FileStatus.READY_TO_START_GROWING
