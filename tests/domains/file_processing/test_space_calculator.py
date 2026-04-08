"""Tests for SpaceCalculator — 0 mocks, pure logic."""

import pytest

from app.domains.file_processing.space_calculator import SpaceCalculator

GB = 1024**3


class TestRequiredSpace:
    def test_includes_all_margins(self):
        calc = SpaceCalculator(safety_margin_gb=1.0, min_free_after_copy_gb=2.0)
        file_size = 5 * GB
        required = calc.required_space(file_size)
        assert required == file_size + 1 * GB + 2 * GB

    def test_zero_margins(self):
        calc = SpaceCalculator(safety_margin_gb=0.0, min_free_after_copy_gb=0.0)
        assert calc.required_space(1000) == 1000

    def test_zero_file_size(self):
        calc = SpaceCalculator(safety_margin_gb=1.0, min_free_after_copy_gb=2.0)
        assert calc.required_space(0) == 1 * GB + 2 * GB


class TestHasSufficientSpace:
    def test_exact_match_sufficient(self):
        calc = SpaceCalculator(safety_margin_gb=1.0, min_free_after_copy_gb=1.0)
        file_size = 1 * GB
        required = calc.required_space(file_size)
        assert calc.has_sufficient_space(required, file_size) is True

    def test_surplus_sufficient(self):
        calc = SpaceCalculator(safety_margin_gb=1.0, min_free_after_copy_gb=1.0)
        assert calc.has_sufficient_space(100 * GB, 1 * GB) is True

    def test_insufficient(self):
        calc = SpaceCalculator(safety_margin_gb=1.0, min_free_after_copy_gb=1.0)
        assert calc.has_sufficient_space(1 * GB, 5 * GB) is False

    def test_one_byte_short(self):
        calc = SpaceCalculator(safety_margin_gb=0.0, min_free_after_copy_gb=0.0)
        assert calc.has_sufficient_space(999, 1000) is False


class TestShortageBytes:
    def test_shortage_when_insufficient(self):
        calc = SpaceCalculator(safety_margin_gb=0.0, min_free_after_copy_gb=0.0)
        assert calc.shortage_bytes(700, 1000) == 300

    def test_no_shortage_when_sufficient(self):
        calc = SpaceCalculator(safety_margin_gb=0.0, min_free_after_copy_gb=0.0)
        assert calc.shortage_bytes(2000, 1000) == 0

    def test_shortage_includes_margins(self):
        calc = SpaceCalculator(safety_margin_gb=1.0, min_free_after_copy_gb=1.0)
        available = 1 * GB
        file_size = 1 * GB
        # Required = 1GB + 1GB + 1GB = 3GB, available = 1GB, shortage = 2GB
        assert calc.shortage_bytes(available, file_size) == 2 * GB


class TestFormatReason:
    def test_sufficient_format(self):
        calc = SpaceCalculator(safety_margin_gb=1.0, min_free_after_copy_gb=1.0)
        reason = calc.format_reason(100 * GB, 5 * GB)
        assert "Sufficient" in reason
        assert "100.0" in reason

    def test_insufficient_format(self):
        calc = SpaceCalculator(safety_margin_gb=1.0, min_free_after_copy_gb=1.0)
        reason = calc.format_reason(1 * GB, 5 * GB)
        assert "Insufficient" in reason
        assert "shortage" in reason

    def test_zero_file_size_format(self):
        calc = SpaceCalculator(safety_margin_gb=0.0, min_free_after_copy_gb=0.0)
        reason = calc.format_reason(10 * GB, 0)
        assert "0.0GB file" in reason


class TestNegativeFileSize:
    def test_negative_file_size_treated_as_zero(self):
        calc = SpaceCalculator(safety_margin_gb=1.0, min_free_after_copy_gb=2.0)
        assert calc.required_space(-100) == 1 * GB + 2 * GB


class TestLargeValues:
    def test_terabyte_file(self):
        calc = SpaceCalculator(safety_margin_gb=10.0, min_free_after_copy_gb=50.0)
        tb = 1024 * GB
        assert calc.has_sufficient_space(2 * tb, 1 * tb) is True
        assert calc.has_sufficient_space(1 * tb, 2 * tb) is False
