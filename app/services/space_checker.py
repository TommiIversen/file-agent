import logging
from typing import Optional

from ..config import Settings
from ..models import SpaceCheckResult
from ..services.storage_monitor import StorageMonitorService


class SpaceChecker:
    def __init__(self, settings: Settings, storage_monitor: StorageMonitorService):
        self._settings = settings
        self._storage_monitor = storage_monitor

        logging.debug("SpaceChecker initialized")

    def check_space_for_file(self, file_size_bytes: int) -> SpaceCheckResult:
        logging.debug(f"Checking space for file of {file_size_bytes} bytes")

        storage_info = self._storage_monitor.get_destination_info()

        if not storage_info:
            return self._create_unavailable_result(file_size_bytes)

        if not storage_info.is_accessible:
            return self._create_inaccessible_result(
                file_size_bytes, storage_info.error_message
            )

        available_bytes = int(storage_info.free_space_gb * (1024 ** 3))
        safety_margin_bytes = int(self._settings.copy_safety_margin_gb * (1024 ** 3))
        minimum_after_copy_bytes = int(
            self._settings.minimum_free_space_after_copy_gb * (1024 ** 3)
        )

        required_bytes = (
                file_size_bytes + safety_margin_bytes + minimum_after_copy_bytes
        )

        has_space = available_bytes >= required_bytes

        reason = self._create_space_reason(
            has_space=has_space,
            available_bytes=available_bytes,
            required_bytes=required_bytes,
            file_size_bytes=file_size_bytes,
            safety_margin_bytes=safety_margin_bytes,
            minimum_after_copy_bytes=minimum_after_copy_bytes,
        )

        return SpaceCheckResult(
            has_space=has_space,
            available_bytes=available_bytes,
            required_bytes=required_bytes,
            file_size_bytes=file_size_bytes,
            safety_margin_bytes=safety_margin_bytes,
            reason=reason,
        )

    def _create_unavailable_result(self, file_size_bytes: int) -> SpaceCheckResult:
        return SpaceCheckResult(
            has_space=False,
            available_bytes=0,
            required_bytes=file_size_bytes,
            file_size_bytes=file_size_bytes,
            safety_margin_bytes=0,
            reason="Storage information unavailable - monitoring may not be running",
        )

    def _create_inaccessible_result(
            self, file_size_bytes: int, error_message: Optional[str]
    ) -> SpaceCheckResult:
        reason = f"Destination not accessible: {error_message or 'Unknown error'}"

        return SpaceCheckResult(
            has_space=False,
            available_bytes=0,
            required_bytes=file_size_bytes,
            file_size_bytes=file_size_bytes,
            safety_margin_bytes=0,
            reason=reason,
        )

    def _create_space_reason(
            self,
            has_space: bool,
            available_bytes: int,
            required_bytes: int,
            file_size_bytes: int,
            safety_margin_bytes: int,
            minimum_after_copy_bytes: int,
    ) -> str:
        available_gb = available_bytes / (1024 ** 3)
        required_gb = required_bytes / (1024 ** 3)
        file_gb = file_size_bytes / (1024 ** 3)

        if has_space:
            return (
                f"Sufficient space: {available_gb:.1f}GB available, "
                f"{required_gb:.1f}GB required for {file_gb:.1f}GB file"
            )
        else:
            shortage_gb = (required_bytes - available_bytes) / (1024 ** 3)
            return (
                f"Insufficient space: {available_gb:.1f}GB available, "
                f"{required_gb:.1f}GB required (shortage: {shortage_gb:.1f}GB). "
                f"File: {file_gb:.1f}GB + safety margins"
            )

    def is_space_check_enabled(self) -> bool:
        return self._settings.enable_pre_copy_space_check

    def get_space_settings_info(self) -> dict:
        return {
            "enabled": self._settings.enable_pre_copy_space_check,
            "safety_margin_gb": self._settings.copy_safety_margin_gb,
            "minimum_after_copy_gb": self._settings.minimum_free_space_after_copy_gb,
            "retry_delay_seconds": self._settings.space_retry_delay_seconds,
            "max_retries": self._settings.max_space_retries,
        }
