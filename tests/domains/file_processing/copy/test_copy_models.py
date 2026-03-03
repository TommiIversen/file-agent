"""
Tests for copy pipeline models: CopyResult and CopyProgress.
"""
from datetime import datetime
from pathlib import Path

from app.domains.file_processing.copy.models import CopyResult, CopyProgress


# ── CopyResult ──────────────────────────────────────────────────────────────

class TestCopyResult:

    def test_successful_result_summary(self):
        result = CopyResult(
            success=True,
            source_path=Path("/src/video.mxf"),
            destination_path=Path("/dst/video.mxf"),
            bytes_copied=100 * 1024 * 1024,  # 100 MB
            elapsed_seconds=10.0,
            start_time=datetime(2026, 1, 1, 12, 0, 0),
            end_time=datetime(2026, 1, 1, 12, 0, 10),
        )
        assert result.success is True
        assert "Copy successful" in result.get_summary()
        assert "video.mxf" in result.get_summary()

    def test_failed_result_summary(self):
        result = CopyResult(
            success=False,
            source_path=Path("/src/video.mxf"),
            destination_path=Path("/dst/video.mxf"),
            bytes_copied=0,
            elapsed_seconds=1.0,
            start_time=datetime(2026, 1, 1, 12, 0, 0),
            end_time=datetime(2026, 1, 1, 12, 0, 1),
            error_message="Network error",
        )
        assert result.success is False
        assert "Copy failed" in result.get_summary()
        assert "Network error" in result.get_summary()

    def test_transfer_rate_bytes_per_sec(self):
        result = CopyResult(
            success=True,
            source_path=Path("/src/a.mxf"),
            destination_path=Path("/dst/a.mxf"),
            bytes_copied=50_000_000,
            elapsed_seconds=5.0,
            start_time=datetime(2026, 1, 1),
            end_time=datetime(2026, 1, 1),
        )
        assert result.transfer_rate_bytes_per_sec == 10_000_000.0

    def test_transfer_rate_zero_elapsed(self):
        result = CopyResult(
            success=True,
            source_path=Path("/src/a.mxf"),
            destination_path=Path("/dst/a.mxf"),
            bytes_copied=50_000_000,
            elapsed_seconds=0.0,
            start_time=datetime(2026, 1, 1),
            end_time=datetime(2026, 1, 1),
        )
        assert result.transfer_rate_bytes_per_sec == 0.0
        assert result.transfer_rate_mb_per_sec == 0.0

    def test_transfer_rate_mb_per_sec(self):
        result = CopyResult(
            success=True,
            source_path=Path("/src/a.mxf"),
            destination_path=Path("/dst/a.mxf"),
            bytes_copied=10 * 1024 * 1024,  # exactly 10 MB
            elapsed_seconds=1.0,
            start_time=datetime(2026, 1, 1),
            end_time=datetime(2026, 1, 1),
        )
        assert result.transfer_rate_mb_per_sec == 10.0

    def test_size_mb(self):
        result = CopyResult(
            success=True,
            source_path=Path("/src/a.mxf"),
            destination_path=Path("/dst/a.mxf"),
            bytes_copied=5 * 1024 * 1024,
            elapsed_seconds=1.0,
            start_time=datetime(2026, 1, 1),
            end_time=datetime(2026, 1, 1),
        )
        assert result.size_mb == 5.0

    def test_optional_fields_default(self):
        result = CopyResult(
            success=True,
            source_path=Path("/src/a.mxf"),
            destination_path=Path("/dst/a.mxf"),
            bytes_copied=1000,
            elapsed_seconds=1.0,
            start_time=datetime(2026, 1, 1),
            end_time=datetime(2026, 1, 1),
        )
        assert result.error_message is None
        assert result.verification_successful is True
        assert result.temp_file_used is False
        assert result.temp_file_path is None


# ── CopyProgress ────────────────────────────────────────────────────────────

class TestCopyProgress:

    def test_progress_percent(self):
        p = CopyProgress(
            bytes_copied=50_000,
            total_bytes=100_000,
            elapsed_seconds=5.0,
            current_rate_bytes_per_sec=10_000.0,
        )
        assert p.progress_percent == 50.0
        assert p.progress_percent_int == 50

    def test_progress_percent_zero_total(self):
        p = CopyProgress(
            bytes_copied=0,
            total_bytes=0,
            elapsed_seconds=0.0,
            current_rate_bytes_per_sec=0.0,
        )
        assert p.progress_percent == 0.0

    def test_progress_caps_at_100(self):
        p = CopyProgress(
            bytes_copied=200,
            total_bytes=100,
            elapsed_seconds=1.0,
            current_rate_bytes_per_sec=100.0,
        )
        assert p.progress_percent == 100.0
        assert p.progress_percent_int == 100

    def test_remaining_bytes(self):
        p = CopyProgress(
            bytes_copied=60_000,
            total_bytes=100_000,
            elapsed_seconds=6.0,
            current_rate_bytes_per_sec=10_000.0,
        )
        assert p.remaining_bytes == 40_000

    def test_remaining_bytes_never_negative(self):
        p = CopyProgress(
            bytes_copied=200,
            total_bytes=100,
            elapsed_seconds=1.0,
            current_rate_bytes_per_sec=100.0,
        )
        assert p.remaining_bytes == 0

    def test_estimated_remaining_seconds(self):
        p = CopyProgress(
            bytes_copied=50_000,
            total_bytes=100_000,
            elapsed_seconds=5.0,
            current_rate_bytes_per_sec=10_000.0,
        )
        assert p.estimated_remaining_seconds == 5.0

    def test_estimated_remaining_zero_rate(self):
        p = CopyProgress(
            bytes_copied=50_000,
            total_bytes=100_000,
            elapsed_seconds=5.0,
            current_rate_bytes_per_sec=0.0,
        )
        assert p.estimated_remaining_seconds == 0.0
