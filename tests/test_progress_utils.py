"""
Tests for progress_utils utilities.

Comprehensive test coverage for all pure functions in progress_utils.py.
Max 300 lines as per 2:1 test ratio (280 lines production code).

Part of Fase 1.2 refactoring tests.
"""

from app.utils.progress_utils import (
    should_report_progress,
    format_progress_info,
    create_simple_progress_bar,
    format_bytes_human_readable,
    calculate_transfer_rate,
    format_transfer_rate_human_readable,
    estimate_time_remaining,
)


class TestShouldReportProgress:
    """Test should_report_progress function."""

    def test_first_update_at_interval(self):
        """Test first update when reaching interval."""
        assert should_report_progress(5, -1, 5) is True
        assert should_report_progress(3, -1, 5) is False

    def test_interval_boundary_updates(self):
        """Test updates at interval boundaries."""
        assert should_report_progress(10, 5, 5) is True
        assert should_report_progress(15, 10, 5) is True
        assert should_report_progress(7, 5, 5) is False

    def test_completion_always_reports(self):
        """Test that completion is always reported."""
        assert should_report_progress(99, 95, 5, is_complete=True) is True
        assert should_report_progress(97, 95, 5, is_complete=True) is True

    def test_no_change_no_update(self):
        """Test no update when progress hasn't changed."""
        assert should_report_progress(10, 10, 5) is False

    def test_different_intervals(self):
        """Test with different update intervals."""
        assert should_report_progress(10, 0, 10) is True
        assert should_report_progress(1, -1, 1) is True
        assert should_report_progress(25, 20, 25) is True



class TestFormatProgressInfo:
    """Test format_progress_info function."""

    def test_basic_formatting(self):
        """Test basic progress info formatting."""
        info = format_progress_info(50.0, 512000, 1024000)

        assert info["percent"] == 50.0
        assert info["bytes_copied"] == 512000
        assert info["total_bytes"] == 1024000
        assert info["bytes_remaining"] == 512000
        assert info["bytes_copied_kb"] == 500.0
        assert info["bytes_copied_mb"] == 0.49
        assert info["is_complete"] is False
        assert "progress_bar" in info

    def test_completion_formatting(self):
        """Test formatting when complete."""
        info = format_progress_info(100.0, 1024, 1024)

        assert info["is_complete"] is True
        assert info["bytes_remaining"] == 0

    def test_over_completion(self):
        """Test formatting when bytes exceed total."""
        info = format_progress_info(100.0, 1200, 1000)

        assert info["bytes_remaining"] == 0  # Should not be negative


class TestCreateSimpleProgressBar:
    """Test create_simple_progress_bar function."""

    def test_empty_progress_bar(self):
        """Test empty progress bar."""
        bar = create_simple_progress_bar(0.0, 10)
        assert bar == "[          ]"

    def test_half_progress_bar(self):
        """Test half-filled progress bar."""
        bar = create_simple_progress_bar(50.0, 10)
        assert bar == "[#####     ]"

    def test_full_progress_bar(self):
        """Test full progress bar."""
        bar = create_simple_progress_bar(100.0, 10)
        assert bar == "[##########]"

    def test_different_widths(self):
        """Test different progress bar widths."""
        bar = create_simple_progress_bar(25.0, 4)
        assert bar == "[#   ]"

        bar = create_simple_progress_bar(75.0, 8)
        assert bar == "[######  ]"

    def test_edge_cases(self):
        """Test edge cases for progress bar."""
        bar = create_simple_progress_bar(-10.0, 5)
        assert bar == "[     ]"  # Negative becomes 0

        bar = create_simple_progress_bar(150.0, 5)
        assert bar == "[#####]"  # Over 100% becomes 100%


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


