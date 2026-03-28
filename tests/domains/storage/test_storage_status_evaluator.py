"""Tests for StorageStatusEvaluator — 0 mocks, pure logic."""

from app.domains.storage.storage_status_evaluator import StorageStatusEvaluator
from app.models import StorageStatus


class TestEvaluate:
    def test_ok_plenty_of_space(self):
        result = StorageStatusEvaluator.evaluate(
            free_gb=100.0,
            warning_threshold_gb=20.0,
            critical_threshold_gb=5.0,
            is_accessible=True,
            has_write_access=True,
        )
        assert result == StorageStatus.OK

    def test_warning_below_threshold(self):
        result = StorageStatusEvaluator.evaluate(
            free_gb=15.0,
            warning_threshold_gb=20.0,
            critical_threshold_gb=5.0,
            is_accessible=True,
            has_write_access=True,
        )
        assert result == StorageStatus.WARNING

    def test_critical_below_threshold(self):
        result = StorageStatusEvaluator.evaluate(
            free_gb=3.0,
            warning_threshold_gb=20.0,
            critical_threshold_gb=5.0,
            is_accessible=True,
            has_write_access=True,
        )
        assert result == StorageStatus.CRITICAL

    def test_critical_no_write_access(self):
        result = StorageStatusEvaluator.evaluate(
            free_gb=100.0,
            warning_threshold_gb=20.0,
            critical_threshold_gb=5.0,
            is_accessible=True,
            has_write_access=False,
        )
        assert result == StorageStatus.CRITICAL

    def test_error_not_accessible(self):
        result = StorageStatusEvaluator.evaluate(
            free_gb=100.0,
            warning_threshold_gb=20.0,
            critical_threshold_gb=5.0,
            is_accessible=False,
            has_write_access=True,
        )
        assert result == StorageStatus.ERROR

    def test_not_accessible_takes_precedence_over_critical(self):
        result = StorageStatusEvaluator.evaluate(
            free_gb=0.0,
            warning_threshold_gb=20.0,
            critical_threshold_gb=5.0,
            is_accessible=False,
            has_write_access=False,
        )
        assert result == StorageStatus.ERROR

    def test_exact_warning_boundary(self):
        """At exactly warning_threshold_gb, should be OK (not below)."""
        result = StorageStatusEvaluator.evaluate(
            free_gb=20.0,
            warning_threshold_gb=20.0,
            critical_threshold_gb=5.0,
            is_accessible=True,
            has_write_access=True,
        )
        assert result == StorageStatus.OK

    def test_exact_critical_boundary(self):
        """At exactly critical_threshold_gb, should be WARNING (not CRITICAL)."""
        result = StorageStatusEvaluator.evaluate(
            free_gb=5.0,
            warning_threshold_gb=20.0,
            critical_threshold_gb=5.0,
            is_accessible=True,
            has_write_access=True,
        )
        assert result == StorageStatus.WARNING

    def test_zero_free_space(self):
        result = StorageStatusEvaluator.evaluate(
            free_gb=0.0,
            warning_threshold_gb=20.0,
            critical_threshold_gb=5.0,
            is_accessible=True,
            has_write_access=True,
        )
        assert result == StorageStatus.CRITICAL


class TestBuildErrorMessage:
    def test_not_accessible(self):
        msg = StorageStatusEvaluator.build_error_message(
            is_accessible=False, has_write_access=True,
            free_gb=100.0, critical_threshold_gb=5.0,
        )
        assert msg == "Path is not accessible"

    def test_no_write_access(self):
        msg = StorageStatusEvaluator.build_error_message(
            is_accessible=True, has_write_access=False,
            free_gb=100.0, critical_threshold_gb=5.0,
        )
        assert msg == "No write access"

    def test_critical_space(self):
        msg = StorageStatusEvaluator.build_error_message(
            is_accessible=True, has_write_access=True,
            free_gb=2.5, critical_threshold_gb=5.0,
        )
        assert msg is not None
        assert "2.5" in msg

    def test_ok_returns_none(self):
        msg = StorageStatusEvaluator.build_error_message(
            is_accessible=True, has_write_access=True,
            free_gb=100.0, critical_threshold_gb=5.0,
        )
        assert msg is None
