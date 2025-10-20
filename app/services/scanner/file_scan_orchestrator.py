# This class is responsible solely for coordinating file scanning operations, adhering to SRP.
import asyncio
import logging
from datetime import datetime
from typing import Optional, Set
from app.models import FileStatus, TrackedFile
from app.config import Settings  # Add proper Settings import
from app.services.state_manager import StateManager
from app.services.growing_file_detector import GrowingFileDetector
from .domain_objects import FilePath, FileMetadata, ScanConfiguration
from .file_discovery_service import FileDiscoveryService
from .file_stability_tracker import FileStabilityTracker
from .file_cleanup_service import FileCleanupService
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.storage_monitor import StorageMonitorService


class FileScanOrchestrator:
    """
    Orchestrator that coordinates file scanning operations between focused services.

    Single Responsibility: Coordination of file scanning workflow
    """

    def __init__(
        self,
        config: ScanConfiguration,
        state_manager: StateManager,
        storage_monitor: Optional["StorageMonitorService"] = None,
        settings: Optional[Settings] = None,  # Add real settings parameter
    ):
        self.config = config
        self.state_manager = state_manager
        self.storage_monitor = storage_monitor
        self.settings = settings  # Store real settings
        self._running = False

        # Composed focused services
        self.discovery_service = FileDiscoveryService(config)
        self.stability_tracker = FileStabilityTracker(config)
        self.cleanup_service = FileCleanupService(config, state_manager)

        # Growing file support - USE REAL SETTINGS, NOT MOCK!
        self.growing_file_detector = None
        if config.enable_growing_file_support and settings:
            # Use the REAL settings object - no more mock bullshit!
            self.growing_file_detector = GrowingFileDetector(
                settings,  # Real settings object
                state_manager
            )
            logging.info("Growing file support enabled")

        logging.info("FileScanOrchestrator initialized")
        logging.info(f"Monitoring: {config.source_directory}")
        logging.info(f"File stability: {config.file_stable_time_seconds}s")
        logging.info(f"Polling interval: {config.polling_interval_seconds}s")

    async def start_scanning(self) -> None:
        """Start the continuous file scanning loop."""
        if self._running:
            logging.warning("Scanner is already running")
            return

        self._running = True
        logging.info("File Scanner started")

        # Start growing file monitoring if enabled
        if self.growing_file_detector:
            await self.growing_file_detector.start_monitoring()

        try:
            await self._scan_folder_loop()
        except asyncio.CancelledError:
            logging.info("File Scanner was cancelled")
            raise
        except Exception as e:
            logging.error(f"Error in scanning loop: {e}")
            raise
        finally:
            # Stop growing file monitoring
            if self.growing_file_detector:
                await self.growing_file_detector.stop_monitoring()

            self._running = False
            logging.info("File Scanner stopped")

    def stop_scanning(self) -> None:
        """Stop file scanning loop."""
        self._running = False
        logging.info("File Scanner stop requested")

    async def _scan_folder_loop(self) -> None:
        """Main scanning loop - orchestrates one complete scan iteration."""
        while self._running:
            try:
                await self._execute_scan_iteration()
                await asyncio.sleep(self.config.polling_interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logging.error(f"Error in scan iteration: {e}")
                await asyncio.sleep(5)

    async def _execute_scan_iteration(self) -> None:
        """Execute one complete scan iteration with timing."""
        scan_start = datetime.now()

        await self._discover_and_cleanup_files()
        await self._process_and_stabilize_files()

        scan_duration = (datetime.now() - scan_start).total_seconds()
        logging.debug(f"Scan iteration completed in {scan_duration:.2f}s")

    async def _discover_and_cleanup_files(self) -> None:
        """Handle file discovery and cleanup operations."""
        current_files = await self.discovery_service.discover_all_files()
        await self.cleanup_service.cleanup_missing_files(current_files)

        current_file_paths = {fp.path for fp in current_files}
        self.stability_tracker.cleanup_tracking_for_missing_files(current_file_paths)
        await self.cleanup_service.cleanup_old_completed_files()

    async def _process_and_stabilize_files(self) -> None:
        """Handle file processing and stability checking."""
        current_files = await self.discovery_service.discover_all_files()
        await self._process_discovered_files(current_files)
        await self._check_file_stability()

    async def _process_discovered_files(self, current_files: Set[FilePath]) -> None:
        """Process all discovered files with UUID-based event sourcing - StateManager as single source of truth."""
        for file_path_obj in current_files:
            try:
                file_path = file_path_obj.path

                # Use StateManager as SINGLE source of truth
                existing_file = await self.state_manager.get_file_by_path(file_path)
                if existing_file is not None:
                    # File exists - check for changes using UUID precision  
                    await self._check_existing_file_changes(existing_file, file_path)
                    continue  # Skip to next file

                # File is NEW or RETURNED after REMOVED
                # StateManager handles UUID generation automatically
                metadata = await FileMetadata.from_path(file_path)
                if metadata is None:
                    continue  # Skip files we can't read

                # Skip empty files
                if metadata.is_empty():
                    logging.debug(f"Skipping empty file: {metadata.path.name}")
                    continue

                # Add new file - StateManager generates UUID automatically
                tracked_file = await self.state_manager.add_file(
                    file_path=file_path,
                    file_size=metadata.size,
                    last_write_time=metadata.last_write_time,
                )

                # Initialize stability tracking
                self.stability_tracker.initialize_file_tracking(
                    file_path, metadata.last_write_time
                )

                # EVENT SOURCING LOGGING - Show UUID for audit trail
                logging.info(
                    f"NEW FILE: {metadata.path.name} ({metadata.size} bytes) "
                    f"[UUID: {tracked_file.id[:8]}...]"
                )

            except Exception as e:
                logging.error(f"Error processing file {file_path_obj.path}: {e}")

    async def _check_existing_file_changes(self, tracked_file, file_path: str) -> None:
        """Check for file changes using precise UUID-based operations - StateManager as single source of truth."""
        metadata = await FileMetadata.from_path(file_path)
        if metadata is None:
            return

        # Check for size changes
        if metadata.size != tracked_file.file_size:
            logging.info(
                f"SIZE CHANGE: {tracked_file.file_path} "
                f"({tracked_file.file_size} → {metadata.size} bytes) "
                f"[UUID: {tracked_file.id[:8]}...]"
            )
            
            # Use UUID-based update for precision - NO extra tracking needed!
            await self.state_manager.update_file_status_by_id(
                file_id=tracked_file.id,
                status=tracked_file.status,  # Keep current status
                file_size=metadata.size,
                last_write_time=metadata.last_write_time
            )

    async def _check_file_stability(self) -> None:
        """Check stability for all Discovered files and promote stable ones to Ready."""
        try:
            # Get all files that need stability checking
            discovered_files = await self.state_manager.get_files_by_status(
                FileStatus.DISCOVERED
            )
            growing_files = []

            if self.growing_file_detector:
                growing_files = await self.state_manager.get_files_by_status(
                    FileStatus.GROWING
                )

            all_files_to_check = discovered_files + growing_files

            for tracked_file in all_files_to_check:
                file_path = tracked_file.file_path

                # Check if file still exists
                metadata = await FileMetadata.from_path(file_path)
                if metadata is None:
                    continue

                if self.growing_file_detector:
                    # Use growing file detection logic - simplified for now
                    await self._handle_growing_file_logic(metadata, tracked_file)
                else:
                    # Use traditional stability logic
                    await self._handle_traditional_stability_logic(metadata, tracked_file)

        except Exception as e:
            logging.error(f"Error in stability check: {e}")

    async def _handle_growing_file_logic(self, metadata: FileMetadata, tracked_file: TrackedFile) -> None:
        """Handle file using growing file detection logic with UUID precision - StateManager as single source of truth."""
        file_path = metadata.path.path

        # Update growth tracking
        await self.growing_file_detector.update_file_growth_info(
            file_path, metadata.size
        )

        # Check growth status
        recommended_status, growth_info = await self.growing_file_detector.check_file_growth_status(tracked_file)

        # Update file status if it changed - USE UUID for precision!
        if recommended_status != tracked_file.status:
            await self.state_manager.update_file_status_by_id(
                file_id=tracked_file.id,  # Precise UUID reference
                status=recommended_status, 
                file_size=metadata.size
            )
            logging.info(f"GROWTH UPDATE: {file_path} -> {recommended_status} [UUID: {tracked_file.id[:8]}...]")

    async def _handle_traditional_stability_logic(self, metadata: FileMetadata, tracked_file) -> None:
        """Handle file using traditional stability logic with UUID precision - StateManager as single source of truth."""
        file_path = metadata.path.path

        # Check if file size changed
        if metadata.size != tracked_file.file_size:
            # Use UUID-based update for precision
            await self.state_manager.update_file_status_by_id(
                file_id=tracked_file.id,  # Precise UUID reference
                status=FileStatus.DISCOVERED,  # Reset due to change
                file_size=metadata.size,
            )
            logging.debug(f"SIZE UPDATE: {file_path} -> {metadata.size} bytes [UUID: {tracked_file.id[:8]}...]")

        # Check stability
        is_stable = await self.stability_tracker.check_file_stability(metadata)
        if is_stable:
            # Use UUID-based update for precision
            await self.state_manager.update_file_status_by_id(
                file_id=tracked_file.id,  # Precise UUID reference
                status=FileStatus.READY
            )
            logging.info(f"STABLE: {file_path} -> READY [UUID: {tracked_file.id[:8]}...]")
