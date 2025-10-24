import logging
from typing import TYPE_CHECKING

from app.config import Settings
from app.services.state_manager import StateManager
from .domain_objects import ScanConfiguration
from .file_scanner import FileScanner

if TYPE_CHECKING:
    from app.services.storage_monitor import StorageMonitorService
    from app.services.websocket_manager import WebSocketManager


class FileScannerService:

    def __init__(
            self,
            settings: Settings,
            state_manager: StateManager,
            storage_monitor: "StorageMonitorService" = None,
            websocket_manager: "WebSocketManager" = None,
    ):
        self._websocket_manager = websocket_manager
        
        config = ScanConfiguration(
            source_directory=settings.source_directory,
            polling_interval_seconds=settings.polling_interval_seconds,
            file_stable_time_seconds=settings.file_stable_time_seconds,
            enable_growing_file_support=settings.enable_growing_file_support,
            growing_file_min_size_mb=settings.growing_file_min_size_mb,
            keep_files_hours=settings.keep_files_hours,
            growing_file_poll_interval_seconds=settings.growing_file_poll_interval_seconds,
            growing_file_safety_margin_mb=settings.growing_file_safety_margin_mb,
            growing_file_growth_timeout_seconds=settings.growing_file_growth_timeout_seconds,
            growing_file_chunk_size_kb=settings.growing_file_chunk_size_kb,
        )

        self.orchestrator = FileScanner(
            config, state_manager, storage_monitor, settings
        )

        logging.info("FileScannerService initialized with refactored architecture")

    async def start_scanning(self) -> None:
        await self.orchestrator.start_scanning()
        
        # Broadcast correct scanner status when actually started
        if self._websocket_manager:
            try:
                is_scanning = self.is_scanning()
                await self._websocket_manager.broadcast_scanner_status(scanning=is_scanning, paused=not is_scanning)
                logging.debug(f"Broadcasted scanner status on start: scanning={is_scanning}")
            except Exception as e:
                logging.warning(f"Failed to broadcast scanner status on start: {e}")

    async def stop_scanning(self) -> None:
        await self.orchestrator.stop_scanning()

        if self._websocket_manager:
            try:
                is_scanning = self.is_scanning()
                await self._websocket_manager.broadcast_scanner_status(scanning=is_scanning, paused=not is_scanning)
                logging.debug(f"Broadcasted scanner status on stop: scanning={is_scanning}")
            except Exception as e:
                logging.warning(f"Failed to broadcast scanner status on stop: {e}")


    def is_scanning(self) -> bool:
        """Check if the scanner is currently running"""
        return self.orchestrator._running
