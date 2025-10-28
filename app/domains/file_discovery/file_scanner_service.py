"""
File Scanner Service using CQRS for file discovery operations.
Acts as a CQRS adapter around the core FileScanner logic.
"""
import logging
from typing import Optional, TYPE_CHECKING

from app.config import Settings
from app.core.events.event_bus import DomainEventBus
from app.core.events.scanner_events import ScannerStatusChangedEvent
from app.core.cqrs.command_bus import CommandBus
from app.core.cqrs.query_bus import QueryBus
from app.domains.file_discovery.file_scanner import FileScanner
from app.domains.file_discovery.domain_objects import ScanConfiguration

if TYPE_CHECKING:
    from app.services.storage_monitor import StorageMonitorService


class FileScannerService:
    """
    CQRS-based File Scanner Service adapter.
    Wraps the core FileScanner logic and provides CQRS integration.
    """

    def __init__(
        self,
        settings: Settings,
        command_bus: CommandBus,
        query_bus: QueryBus,
        storage_monitor: "StorageMonitorService" = None,
        event_bus: Optional[DomainEventBus] = None,
    ):
        self._command_bus = command_bus
        self._query_bus = query_bus
        self._event_bus = event_bus
        
        # Create ScanConfiguration for the core FileScanner
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
        
        # Import StateManager here to avoid circular import
        # from app.dependencies import get_state_manager
        # state_manager = get_state_manager()
        
        # Create the core FileScanner with CQRS integration
        self._file_scanner = FileScanner(
            config=config,
            command_bus=command_bus,
            query_bus=query_bus,
            storage_monitor=storage_monitor,
            settings=settings,
            event_bus=event_bus,
        )
        
        logging.info("FileScannerService initialized as CQRS adapter around FileScanner")

    async def start_scanning(self) -> None:
        """Start the file scanning process."""
        if self._event_bus:
            try:
                await self._event_bus.publish(
                    ScannerStatusChangedEvent(is_scanning=True, is_paused=False)
                )
                logging.debug("Published ScannerStatusChangedEvent on start")
            except Exception as e:
                logging.warning(f"Failed to publish ScannerStatusChangedEvent on start: {e}")

        # Delegate to the core FileScanner
        await self._file_scanner.start_scanning()
        logging.info("File scanning started")

    async def stop_scanning(self) -> None:
        """Stop the file scanning process."""
        # Delegate to the core FileScanner
        await self._file_scanner.stop_scanning()
        
        if self._event_bus:
            try:
                await self._event_bus.publish(
                    ScannerStatusChangedEvent(is_scanning=False, is_paused=False)
                )
                logging.debug("Published ScannerStatusChangedEvent on stop")
            except Exception as e:
                logging.warning(f"Failed to publish ScannerStatusChangedEvent on stop: {e}")

        logging.info("File scanning stopped")

    def is_scanning(self) -> bool:
        """Check if the scanner is currently running."""
        return self._file_scanner._running if self._file_scanner else False

    async def get_active_file_by_path(self, file_path: str):
        """Get active file by path using CQRS query."""
        from app.domains.file_discovery.queries import GetActiveFileByPathQuery
        query = GetActiveFileByPathQuery(file_path=file_path)
        return await self._query_bus.execute(query)
