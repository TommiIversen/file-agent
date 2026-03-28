"""Tests for CooldownChecker — 0 mocks, pure logic."""

from datetime import datetime, timedelta

from app.domains.file_discovery.cooldown_checker import CooldownChecker
from app.models import FileStatus, TrackedFile


def _make_file(
    status: FileStatus = FileStatus.SPACE_ERROR,
    space_error_at: datetime | None = None,
) -> TrackedFile:
    return TrackedFile(
        file_path="/test/file.mxf",
        status=status,
        space_error_at=space_error_at,
    )


class TestIsInCooldown:
    def test_active_cooldown(self):
        error_time = datetime(2025, 1, 1, 12, 0, 0)
        now = datetime(2025, 1, 1, 12, 30, 0)  # 30 min later
        in_cd, remaining = CooldownChecker.is_in_cooldown(error_time, 60, now)
        assert in_cd is True
        assert remaining == pytest.approx(30.0)

    def test_expired_cooldown(self):
        error_time = datetime(2025, 1, 1, 12, 0, 0)
        now = datetime(2025, 1, 1, 13, 30, 0)  # 90 min later
        in_cd, remaining = CooldownChecker.is_in_cooldown(error_time, 60, now)
        assert in_cd is False
        assert remaining == 0.0

    def test_exact_boundary(self):
        error_time = datetime(2025, 1, 1, 12, 0, 0)
        now = datetime(2025, 1, 1, 13, 0, 0)  # Exactly 60 min later
        in_cd, remaining = CooldownChecker.is_in_cooldown(error_time, 60, now)
        assert in_cd is False

    def test_just_before_expiry(self):
        error_time = datetime(2025, 1, 1, 12, 0, 0)
        now = error_time + timedelta(minutes=59, seconds=59)
        in_cd, remaining = CooldownChecker.is_in_cooldown(error_time, 60, now)
        assert in_cd is True
        assert remaining > 0

    def test_zero_cooldown(self):
        error_time = datetime(2025, 1, 1, 12, 0, 0)
        now = datetime(2025, 1, 1, 12, 0, 0)
        in_cd, remaining = CooldownChecker.is_in_cooldown(error_time, 0, now)
        assert in_cd is False


class TestShouldSkipSpaceError:
    def test_skip_when_in_cooldown(self):
        now = datetime(2025, 1, 1, 12, 30, 0)
        f = _make_file(
            status=FileStatus.SPACE_ERROR,
            space_error_at=datetime(2025, 1, 1, 12, 0, 0),
        )
        skip, reason = CooldownChecker.should_skip_space_error(f, 60, now)
        assert skip is True
        assert "cooldown" in reason.lower()

    def test_no_skip_when_expired(self):
        now = datetime(2025, 1, 1, 14, 0, 0)
        f = _make_file(
            status=FileStatus.SPACE_ERROR,
            space_error_at=datetime(2025, 1, 1, 12, 0, 0),
        )
        skip, reason = CooldownChecker.should_skip_space_error(f, 60, now)
        assert skip is False
        assert reason == ""

    def test_no_skip_when_not_space_error(self):
        now = datetime(2025, 1, 1, 12, 0, 0)
        f = _make_file(status=FileStatus.DISCOVERED)
        skip, reason = CooldownChecker.should_skip_space_error(f, 60, now)
        assert skip is False
        assert reason == ""

    def test_no_skip_when_no_timestamp(self):
        now = datetime(2025, 1, 1, 12, 0, 0)
        f = _make_file(status=FileStatus.SPACE_ERROR, space_error_at=None)
        skip, reason = CooldownChecker.should_skip_space_error(f, 60, now)
        assert skip is False


import pytest
