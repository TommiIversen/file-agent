import logging
from typing import TYPE_CHECKING, Optional

from app.config import Settings
from app.core.events.event_bus import DomainEventBus
from app.core.events.scanner_events import ScannerStatusChangedEvent
from app.services.state_manager import StateManager
from ...services.scanner.domain_objects import ScanConfiguration
from ...services.scanner.file_scanner import FileScanner

if TYPE_CHECKING:
    from app.services.storage_monitor import StorageMonitorService


class FileScannerService:
    def __init__(
        self,
        settings: Settings,
        state_manager: StateManager,
        storage_monitor: "StorageMonitorService" = None,
        event_bus: Optional[DomainEventBus] = None,
    ):
        self._event_bus = event_bus

        config = ScanConfiguration(
            source_directory=settings.source_directory,
            polling_interval_seconds=settings.polling_interval_seconds,
            file_stable_time_seconds=settings.file_stable_time_seconds,
            keep_files_hours=settings.keep_files_hours,
            growing_file_poll_interval_seconds=settings.growing_file_poll_interval_seconds,
            growing_file_safety_margin_mb=settings.growing_file_safety_margin_mb,
            growing_file_growth_timeout_seconds=settings.growing_file_growth_timeout_seconds,
            growing_file_chunk_size_kb=settings.growing_file_chunk_size_kb,
        )

        self.orchestrator = FileScanner(
            config, state_manager, storage_monitor, settings, event_bus=self._event_bus
        )

        logging.info("FileScannerService initialized with refactored architecture")

    async def start_scanning(self) -> None:
        await self.orchestrator.start_scanning()
        if self._event_bus:
            try:
                is_scanning = self.is_scanning()
                await self._event_bus.publish(
                    ScannerStatusChangedEvent(is_scanning=is_scanning, is_paused=not is_scanning)
                )
                logging.debug(f"Published ScannerStatusChangedEvent on start: scanning={is_scanning}")
            except Exception as e:
                logging.warning(f"Failed to publish ScannerStatusChangedEvent on start: {e}")


    async def stop_scanning(self) -> None:
        await self.orchestrator.stop_scanning()

        if self._event_bus:
            try:
                is_scanning = self.is_scanning()
                await self._event_bus.publish(
                    ScannerStatusChangedEvent(is_scanning=is_scanning, is_paused=not is_scanning)
                )
                logging.debug(f"Published ScannerStatusChangedEvent on stop: scanning={is_scanning}")
            except Exception as e:
                logging.warning(f"Failed to publish ScannerStatusChangedEvent on stop: {e}")

    def is_scanning(self) -> bool:
        """Check if the scanner is currently running"""
        return self.orchestrator._running
