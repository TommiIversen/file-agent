"""
Tests for progress_utils utilities.

Comprehensive test coverage for all pure functions in progress_utils.py.
Max 300 lines as per 2:1 test ratio (280 lines production code).

Part of Fase 1.2 refactoring tests.
"""

from app.utils.progress_utils import (
    format_bytes_human_readable,
    calculate_transfer_rate,
    format_transfer_rate_human_readable,
    estimate_time_remaining,
)



class TestFormatBytesHumanReadable:
    """Test format_bytes_human_readable function."""

    def test_bytes(self):
        """Test formatting bytes."""
        assert format_bytes_human_readable(512) == "512 B"
        assert format_bytes_human_readable(1023) == "1023 B"

    def test_kilobytes(self):
        """Test formatting kilobytes."""
        assert format_bytes_human_readable(1024) == "1.0 KB"
        assert format_bytes_human_readable(1536) == "1.5 KB"
        assert format_bytes_human_readable(2560) == "2.5 KB"

    def test_megabytes(self):
        """Test formatting megabytes."""
        assert format_bytes_human_readable(1048576) == "1.0 MB"
        assert format_bytes_human_readable(1572864) == "1.5 MB"

    def test_gigabytes(self):
        """Test formatting gigabytes."""
        assert format_bytes_human_readable(1073741824) == "1.0 GB"
        assert format_bytes_human_readable(1610612736) == "1.5 GB"


class TestCalculateTransferRate:
    """Test calculate_transfer_rate function."""

    def test_normal_rate(self):
        """Test normal transfer rate calculation."""
        assert calculate_transfer_rate(1024, 1.0) == 1024.0
        assert calculate_transfer_rate(2048, 2.0) == 1024.0

    def test_zero_time(self):
        """Test zero elapsed time edge case."""
        assert calculate_transfer_rate(1024, 0.0) == 0.0

    def test_negative_time(self):
        """Test negative elapsed time edge case."""
        assert calculate_transfer_rate(1024, -1.0) == 0.0

    def test_zero_bytes(self):
        """Test zero bytes copied."""
        assert calculate_transfer_rate(0, 5.0) == 0.0


class TestFormatTransferRateHumanReadable:
    """Test format_transfer_rate_human_readable function."""

    def test_rate_formatting(self):
        """Test transfer rate formatting."""
        assert format_transfer_rate_human_readable(1024.0) == "1.0 KB/s"
        assert format_transfer_rate_human_readable(1048576.0) == "1.0 MB/s"
        assert format_transfer_rate_human_readable(512.0) == "512 B/s"


class TestEstimateTimeRemaining:
    """Test estimate_time_remaining function."""

    def test_normal_estimation(self):
        """Test normal time estimation."""
        assert estimate_time_remaining(500, 1000, 100.0) == 5.0
        assert estimate_time_remaining(750, 1000, 50.0) == 5.0

    def test_complete_file(self):
        """Test estimation when file is complete."""
        assert estimate_time_remaining(1000, 1000, 100.0) == 0.0

    def test_zero_rate(self):
        """Test estimation with zero transfer rate."""
        assert estimate_time_remaining(500, 1000, 0.0) == 0.0

    def test_negative_rate(self):
        """Test estimation with negative transfer rate."""
        assert estimate_time_remaining(500, 1000, -10.0) == 0.0


