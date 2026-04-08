import logging
from typing import Optional

from app.config import Settings
from app.models import SpaceCheckResult, StorageInfoProvider
from app.domains.file_processing.space_calculator import SpaceCalculator


class SpaceChecker:
    def __init__(self, settings: Settings, storage_monitor: StorageInfoProvider):
        self._settings = settings
        self._storage_monitor = storage_monitor
        self._calculator = SpaceCalculator(
            safety_margin_gb=settings.copy_safety_margin_gb,
            min_free_after_copy_gb=settings.minimum_free_space_after_copy_gb,
        )

        logging.debug("SpaceChecker initialized")

    def check_space_for_file(self, file_size_bytes: int) -> SpaceCheckResult:
        logging.debug(f"Checking space for file of {file_size_bytes} bytes")

        try:
            storage_info = self._storage_monitor.get_destination_info()
        except Exception as e:
            logging.error(f"Error getting storage info: {e}", exc_info=True)
            return self._create_unavailable_result(file_size_bytes)

        if not storage_info:
            return self._create_unavailable_result(file_size_bytes)

        if not storage_info.is_accessible:
            return self._create_inaccessible_result(
                file_size_bytes, storage_info.error_message
            )

        available_bytes = int(storage_info.free_space_gb * (1024**3))
        required_bytes = self._calculator.required_space(file_size_bytes)
        has_space = self._calculator.has_sufficient_space(available_bytes, file_size_bytes)
        reason = self._calculator.format_reason(available_bytes, file_size_bytes)

        return SpaceCheckResult(
            has_space=has_space,
            available_bytes=available_bytes,
            required_bytes=required_bytes,
            file_size_bytes=file_size_bytes,
            safety_margin_bytes=self._calculator.safety_margin_bytes,
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
