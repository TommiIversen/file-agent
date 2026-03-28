"""
Tests for SpaceChecker — pre-copy disk space verification.
Tests the arithmetic, edge cases, and all result paths.
"""
import pytest
from unittest.mock import MagicMock
from datetime import datetime

from app.domains.file_processing.space_checker import SpaceChecker
from app.models import StorageInfo, StorageStatus


def _make_settings(**overrides) -> MagicMock:
    settings = MagicMock()
    settings.copy_safety_margin_gb = overrides.get("copy_safety_margin_gb", 1.0)
    settings.minimum_free_space_after_copy_gb = overrides.get("minimum_free_space_after_copy_gb", 2.0)
    settings.enable_pre_copy_space_check = overrides.get("enable_pre_copy_space_check", True)
    settings.space_retry_delay_seconds = overrides.get("space_retry_delay_seconds", 300)
    settings.max_space_retries = overrides.get("max_space_retries", 6)
    return settings


def _make_storage_info(free_space_gb: float = 100.0, is_accessible: bool = True, error_message: str = None) -> StorageInfo:
    return StorageInfo(
        path="/mnt/dest",
        is_accessible=is_accessible,
        has_write_access=True,
        free_space_gb=free_space_gb,
        total_space_gb=500.0,
        used_space_gb=500.0 - free_space_gb,
        status=StorageStatus.OK if is_accessible else StorageStatus.ERROR,
        warning_threshold_gb=50.0,
        critical_threshold_gb=20.0,
        last_checked=datetime.now(),
        error_message=error_message,
    )


class TestSpaceCheckerSufficientSpace:

    def test_has_space_when_plenty_available(self):
        settings = _make_settings()
        monitor = MagicMock()
        monitor.get_destination_info.return_value = _make_storage_info(free_space_gb=100.0)

        checker = SpaceChecker(settings, monitor)
        # 1 GB file + 1 GB safety + 2 GB min after = 4 GB required, 100 GB available
        result = checker.check_space_for_file(1 * 1024**3)

        assert result.has_space is True
        assert result.available_bytes == 100 * 1024**3
        assert "Sufficient space" in result.reason

    def test_has_space_exact_minimum(self):
        """Available exactly matches required — should pass."""
        settings = _make_settings(copy_safety_margin_gb=0.0, minimum_free_space_after_copy_gb=0.0)
        monitor = MagicMock()
        # 5 GB available, 5 GB file, 0 margins → exactly enough
        monitor.get_destination_info.return_value = _make_storage_info(free_space_gb=5.0)

        checker = SpaceChecker(settings, monitor)
        result = checker.check_space_for_file(5 * 1024**3)

        assert result.has_space is True


class TestSpaceCheckerInsufficientSpace:

    def test_not_enough_space(self):
        settings = _make_settings()
        monitor = MagicMock()
        # 3 GB available, 5 GB file + 1 GB safety + 2 GB min = 8 GB required
        monitor.get_destination_info.return_value = _make_storage_info(free_space_gb=3.0)

        checker = SpaceChecker(settings, monitor)
        result = checker.check_space_for_file(5 * 1024**3)

        assert result.has_space is False
        assert "Insufficient space" in result.reason
        assert result.required_bytes == (5 + 1 + 2) * 1024**3

    def test_shortage_just_below_threshold(self):
        """Available is 1 byte less than required."""
        settings = _make_settings(copy_safety_margin_gb=0.0, minimum_free_space_after_copy_gb=0.0)
        monitor = MagicMock()
        # 4.999... GB available for a 5 GB file
        monitor.get_destination_info.return_value = _make_storage_info(free_space_gb=4.9)

        checker = SpaceChecker(settings, monitor)
        result = checker.check_space_for_file(5 * 1024**3)

        assert result.has_space is False


class TestSpaceCheckerUnavailable:

    def test_storage_info_unavailable(self):
        settings = _make_settings()
        monitor = MagicMock()
        monitor.get_destination_info.return_value = None

        checker = SpaceChecker(settings, monitor)
        result = checker.check_space_for_file(1000)

        assert result.has_space is False
        assert result.available_bytes == 0
        assert "unavailable" in result.reason

    def test_storage_inaccessible_with_error(self):
        settings = _make_settings()
        monitor = MagicMock()
        monitor.get_destination_info.return_value = _make_storage_info(
            is_accessible=False, error_message="Mount point not found"
        )

        checker = SpaceChecker(settings, monitor)
        result = checker.check_space_for_file(1000)

        assert result.has_space is False
        assert "Mount point not found" in result.reason

    def test_storage_inaccessible_no_error_message(self):
        settings = _make_settings()
        monitor = MagicMock()
        monitor.get_destination_info.return_value = _make_storage_info(
            is_accessible=False, error_message=None
        )

        checker = SpaceChecker(settings, monitor)
        result = checker.check_space_for_file(1000)

        assert result.has_space is False
        assert "Unknown error" in result.reason


class TestSpaceCheckerResultFields:

    def test_result_contains_correct_file_size(self):
        settings = _make_settings()
        monitor = MagicMock()
        monitor.get_destination_info.return_value = _make_storage_info(free_space_gb=100.0)

        checker = SpaceChecker(settings, monitor)
        file_size = 3 * 1024**3
        result = checker.check_space_for_file(file_size)

        assert result.file_size_bytes == file_size
        assert result.safety_margin_bytes == 1 * 1024**3  # default 1 GB

    def test_result_required_bytes_calculation(self):
        settings = _make_settings(copy_safety_margin_gb=2.0, minimum_free_space_after_copy_gb=3.0)
        monitor = MagicMock()
        monitor.get_destination_info.return_value = _make_storage_info(free_space_gb=100.0)

        checker = SpaceChecker(settings, monitor)
        file_size = 10 * 1024**3
        result = checker.check_space_for_file(file_size)

        # 10 + 2 + 3 = 15 GB
        assert result.required_bytes == 15 * 1024**3


class TestSpaceCheckerSettingsInfo:

    def test_is_space_check_enabled_true(self):
        settings = _make_settings(enable_pre_copy_space_check=True)
        monitor = MagicMock()
        checker = SpaceChecker(settings, monitor)
        assert checker.is_space_check_enabled() is True

    def test_is_space_check_enabled_false(self):
        settings = _make_settings(enable_pre_copy_space_check=False)
        monitor = MagicMock()
        checker = SpaceChecker(settings, monitor)
        assert checker.is_space_check_enabled() is False

    def test_get_space_settings_info(self):
        settings = _make_settings(
            enable_pre_copy_space_check=True,
            copy_safety_margin_gb=1.5,
            minimum_free_space_after_copy_gb=3.0,
            space_retry_delay_seconds=600,
            max_space_retries=10,
        )
        monitor = MagicMock()
        checker = SpaceChecker(settings, monitor)
        info = checker.get_space_settings_info()

        assert info["enabled"] is True
        assert info["safety_margin_gb"] == 1.5
        assert info["minimum_after_copy_gb"] == 3.0
        assert info["retry_delay_seconds"] == 600
        assert info["max_retries"] == 10


class TestSpaceCheckerZeroBytes:

    def test_zero_byte_file(self):
        """A zero-byte file still needs safety margin + minimum free space."""
        settings = _make_settings()
        monitor = MagicMock()
        monitor.get_destination_info.return_value = _make_storage_info(free_space_gb=5.0)

        checker = SpaceChecker(settings, monitor)
        result = checker.check_space_for_file(0)

        # 0 + 1 GB safety + 2 GB min = 3 GB required, 5 GB available
        assert result.has_space is True
        assert result.file_size_bytes == 0
