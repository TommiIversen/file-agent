"""Tests for GrowthStatusAnalyzer — 0 mocks, pure logic."""

from datetime import datetime, timedelta

from app.domains.file_discovery.growth_status_analyzer import GrowthStatusAnalyzer
from app.models import FileStatus


class TestDetermineStatus:
    def test_growing_under_min_returns_growing(self):
        result = GrowthStatusAnalyzer.determine_status(
            current_size=500,
            previous_size=100,
            growth_stable_since=None,
            current_time=datetime(2025, 1, 1),
            min_size_bytes=1000,
            stability_timeout_seconds=30,
        )
        assert result == FileStatus.GROWING

    def test_growing_above_min_returns_ready_to_start(self):
        result = GrowthStatusAnalyzer.determine_status(
            current_size=2000,
            previous_size=100,
            growth_stable_since=None,
            current_time=datetime(2025, 1, 1),
            min_size_bytes=1000,
            stability_timeout_seconds=30,
        )
        assert result == FileStatus.READY_TO_START_GROWING

    def test_growing_exactly_at_min_returns_ready_to_start(self):
        result = GrowthStatusAnalyzer.determine_status(
            current_size=1000,
            previous_size=500,
            growth_stable_since=None,
            current_time=datetime(2025, 1, 1),
            min_size_bytes=1000,
            stability_timeout_seconds=30,
        )
        assert result == FileStatus.READY_TO_START_GROWING

    def test_just_stopped_growing_returns_growing(self):
        """File stopped growing, no stability timestamp yet."""
        result = GrowthStatusAnalyzer.determine_status(
            current_size=1000,
            previous_size=1000,
            growth_stable_since=None,
            current_time=datetime(2025, 1, 1),
            min_size_bytes=500,
            stability_timeout_seconds=30,
        )
        assert result == FileStatus.GROWING

    def test_stable_long_enough_returns_ready(self):
        now = datetime(2025, 1, 1, 12, 1, 0)
        stable_since = datetime(2025, 1, 1, 12, 0, 0)  # 60 sec ago
        result = GrowthStatusAnalyzer.determine_status(
            current_size=1000,
            previous_size=1000,
            growth_stable_since=stable_since,
            current_time=now,
            min_size_bytes=500,
            stability_timeout_seconds=30,
        )
        assert result == FileStatus.READY

    def test_not_stable_long_enough_returns_growing(self):
        now = datetime(2025, 1, 1, 12, 0, 10)
        stable_since = datetime(2025, 1, 1, 12, 0, 0)  # 10 sec ago
        result = GrowthStatusAnalyzer.determine_status(
            current_size=1000,
            previous_size=1000,
            growth_stable_since=stable_since,
            current_time=now,
            min_size_bytes=500,
            stability_timeout_seconds=30,
        )
        assert result == FileStatus.GROWING

    def test_exact_timeout_boundary_returns_ready(self):
        now = datetime(2025, 1, 1, 12, 0, 30)
        stable_since = datetime(2025, 1, 1, 12, 0, 0)  # Exactly 30 sec
        result = GrowthStatusAnalyzer.determine_status(
            current_size=1000,
            previous_size=1000,
            growth_stable_since=stable_since,
            current_time=now,
            min_size_bytes=500,
            stability_timeout_seconds=30,
        )
        assert result == FileStatus.READY

    def test_shrinking_file_treated_as_size_changed(self):
        """current_size < previous_size: size changed, treated same as growing (matches original)."""
        result = GrowthStatusAnalyzer.determine_status(
            current_size=500,
            previous_size=1000,
            growth_stable_since=None,
            current_time=datetime(2025, 1, 1),
            min_size_bytes=200,
            stability_timeout_seconds=30,
        )
        # current_size != previous_size → size changed → READY_TO_START_GROWING (500 >= 200)
        assert result == FileStatus.READY_TO_START_GROWING


class TestCalculateGrowthRate:
    def test_normal_growth(self):
        rate = GrowthStatusAnalyzer.calculate_growth_rate_mbps(
            current_size=2 * 1024 * 1024,  # 2 MB
            first_seen_size=1 * 1024 * 1024,  # 1 MB
            elapsed_seconds=1.0,
        )
        assert rate == pytest.approx(1.0)

    def test_zero_elapsed(self):
        rate = GrowthStatusAnalyzer.calculate_growth_rate_mbps(
            current_size=2 * 1024 * 1024,
            first_seen_size=1 * 1024 * 1024,
            elapsed_seconds=0.0,
        )
        assert rate == 0.0

    def test_negative_elapsed(self):
        rate = GrowthStatusAnalyzer.calculate_growth_rate_mbps(
            current_size=2 * 1024 * 1024,
            first_seen_size=1 * 1024 * 1024,
            elapsed_seconds=-1.0,
        )
        assert rate == 0.0

    def test_zero_first_seen(self):
        rate = GrowthStatusAnalyzer.calculate_growth_rate_mbps(
            current_size=1000,
            first_seen_size=0,
            elapsed_seconds=1.0,
        )
        assert rate == 0.0

    def test_large_file_rate(self):
        gb = 1024 * 1024 * 1024
        rate = GrowthStatusAnalyzer.calculate_growth_rate_mbps(
            current_size=10 * gb,
            first_seen_size=1 * gb,
            elapsed_seconds=10.0,
        )
        expected_mb = (9 * gb) / (1024 * 1024)
        assert rate == pytest.approx(expected_mb / 10.0)


class TestDetermineStabilityTimestamp:
    def test_still_growing_returns_none(self):
        result = GrowthStatusAnalyzer.determine_stability_timestamp(
            current_size=200, previous_size=100,
            growth_stable_since=datetime(2025, 1, 1),
            current_time=datetime(2025, 1, 2),
        )
        assert result is None

    def test_just_stopped_returns_current_time(self):
        now = datetime(2025, 1, 1, 12, 0, 0)
        result = GrowthStatusAnalyzer.determine_stability_timestamp(
            current_size=100, previous_size=100,
            growth_stable_since=None,
            current_time=now,
        )
        assert result == now

    def test_already_stable_keeps_original(self):
        original = datetime(2025, 1, 1, 11, 0, 0)
        result = GrowthStatusAnalyzer.determine_stability_timestamp(
            current_size=100, previous_size=100,
            growth_stable_since=original,
            current_time=datetime(2025, 1, 1, 12, 0, 0),
        )
        assert result == original


import pytest
