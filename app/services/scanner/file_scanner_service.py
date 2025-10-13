# This class is responsible solely for providing a clean interface to file scanning operations, adhering to SRP.
import logging
from app.config import Settings
from app.services.state_manager import StateManager
from .domain_objects import ScanConfiguration
from .file_scan_orchestrator import FileScanOrchestrator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.storage_monitor import StorageMonitorService


class FileScannerService:
    """
    Clean interface to file scanning operations, delegating to focused services.

    Single Responsibility: Provide a stable API interface for file scanning
    """

    def __init__(
        self,
        settings: Settings,
        state_manager: StateManager,
        storage_monitor: "StorageMonitorService" = None,
    ):
        # Convert settings to configuration object to eliminate long parameter lists
        config = ScanConfiguration(
            source_directory=settings.source_directory,
            polling_interval_seconds=settings.polling_interval_seconds,
            file_stable_time_seconds=settings.file_stable_time_seconds,
            enable_growing_file_support=settings.enable_growing_file_support,
            growing_file_min_size_mb=settings.growing_file_min_size_mb,
            keep_completed_files_hours=settings.keep_completed_files_hours,
            max_completed_files_in_memory=settings.max_completed_files_in_memory,
            # Add all growing file settings
            growing_file_poll_interval_seconds=settings.growing_file_poll_interval_seconds,
            growing_file_safety_margin_mb=settings.growing_file_safety_margin_mb,
            growing_file_growth_timeout_seconds=settings.growing_file_growth_timeout_seconds,
            growing_file_chunk_size_kb=settings.growing_file_chunk_size_kb,
        )

        # Delegate all operations to the orchestrator
        self.orchestrator = FileScanOrchestrator(config, state_manager, storage_monitor, settings)

        logging.info("FileScannerService initialized with refactored architecture")

    async def start_scanning(self) -> None:
        """Start the continuous file scanning loop."""
        await self.orchestrator.start_scanning()

    def stop_scanning(self) -> None:
        """Stop file scanning loop."""
        self.orchestrator.stop_scanning()

    @property
    def is_running(self) -> bool:
        """Check if scanner is currently running."""
        return self.orchestrator._running
