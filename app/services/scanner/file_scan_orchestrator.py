import asyncio
import logging
from datetime import datetime
from typing import Optional, Set
from typing import TYPE_CHECKING

from app.config import Settings
from app.models import FileStatus, TrackedFile
from app.services.growing_file_detector import GrowingFileDetector
from app.services.state_manager import StateManager
from .domain_objects import FilePath, FileMetadata, ScanConfiguration
from .file_cleanup_service import FileCleanupService
from .file_discovery_service import FileDiscoveryService
from .file_stability_tracker import FileStabilityTracker

if TYPE_CHECKING:
    from app.services.storage_monitor import StorageMonitorService


class FileScanOrchestrator:

    def __init__(
            self,
            config: ScanConfiguration,
            state_manager: StateManager,
            storage_monitor: Optional["StorageMonitorService"] = None,
            settings: Optional[Settings] = None,
    ):
        self.config = config
        self.state_manager = state_manager
        self.storage_monitor = storage_monitor
        self.settings = settings
        self._running = False

        self.discovery_service = FileDiscoveryService(config)
        self.stability_tracker = FileStabilityTracker(config)
        self.cleanup_service = FileCleanupService(config, state_manager)

        self.growing_file_detector = None
        if config.enable_growing_file_support and settings:
            self.growing_file_detector = GrowingFileDetector(settings, state_manager)
            logging.info("Growing file support enabled")

        logging.info("FileScanOrchestrator initialized")
        logging.info(f"Monitoring: {config.source_directory}")
        logging.info(f"File stability: {config.file_stable_time_seconds}s")
        logging.info(f"Polling interval: {config.polling_interval_seconds}s")

    async def start_scanning(self) -> None:
        if self._running:
            logging.warning("Scanner is already running")
            return

        self._running = True
        logging.info("File Scanner started")

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
            if self.growing_file_detector:
                await self.growing_file_detector.stop_monitoring()

            self._running = False
            logging.info("File Scanner stopped")

    def stop_scanning(self) -> None:
        self._running = False
        logging.info("File Scanner stop requested")

    async def _scan_folder_loop(self) -> None:
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
        scan_start = datetime.now()

        await self._discover_and_cleanup_files()
        await self._process_and_stabilize_files()

        scan_duration = (datetime.now() - scan_start).total_seconds()
        logging.debug(f"Scan iteration completed in {scan_duration:.2f}s")

    async def _discover_and_cleanup_files(self) -> None:
        current_files = await self.discovery_service.discover_all_files()
        await self.cleanup_service.cleanup_missing_files(current_files)

        current_file_paths = {fp.path for fp in current_files}
        self.stability_tracker.cleanup_tracking_for_missing_files(current_file_paths)
        await self.cleanup_service.cleanup_old_files()

    async def _process_and_stabilize_files(self) -> None:
        current_files = await self.discovery_service.discover_all_files()
        await self._process_discovered_files(current_files)
        await self._check_file_stability()

    async def _process_discovered_files(self, current_files: Set[FilePath]) -> None:
        for file_path_obj in current_files:
            try:
                file_path = file_path_obj.path

                existing_file = await self.state_manager.get_file_by_path(file_path)
                if existing_file is not None:
                    await self._check_existing_file_changes(existing_file, file_path)
                    continue

                metadata = await FileMetadata.from_path(file_path)
                if metadata is None:
                    continue

                if metadata.is_empty():
                    logging.debug(f"Skipping empty file: {metadata.path.name}")
                    continue

                tracked_file = await self.state_manager.add_file(
                    file_path=file_path,
                    file_size=metadata.size,
                    last_write_time=metadata.last_write_time,
                )

                self.stability_tracker.initialize_file_tracking(
                    file_path, metadata.last_write_time
                )

                logging.info(
                    f"NEW FILE: {metadata.path.name} ({metadata.size} bytes) "
                    f"[UUID: {tracked_file.id[:8]}...]"
                )

            except Exception as e:
                logging.error(f"Error processing file {file_path_obj.path}: {e}")

    async def _check_existing_file_changes(self, tracked_file, file_path: str) -> None:
        metadata = await FileMetadata.from_path(file_path)
        if metadata is None:
            return

        if metadata.size != tracked_file.file_size:
            logging.info(
                f"SIZE CHANGE: {tracked_file.file_path} "
                f"({tracked_file.file_size} → {metadata.size} bytes) "
                f"[UUID: {tracked_file.id[:8]}...]"
            )

            await self.state_manager.update_file_status_by_id(
                file_id=tracked_file.id,
                status=tracked_file.status,
                file_size=metadata.size,
                last_write_time=metadata.last_write_time,
            )

    async def _check_file_stability(self) -> None:
        try:
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

                metadata = await FileMetadata.from_path(file_path)
                if metadata is None:
                    continue

                if self.growing_file_detector:
                    await self._handle_growing_file_logic(metadata, tracked_file)
                else:
                    await self._handle_traditional_stability_logic(
                        metadata, tracked_file
                    )

        except Exception as e:
            logging.error(f"Error in stability check: {e}")

    async def _handle_growing_file_logic(
            self, metadata: FileMetadata, tracked_file: TrackedFile
    ) -> None:
        file_path = metadata.path.path

        await self.growing_file_detector.update_file_growth_info(
            tracked_file, metadata.size
        )

        (
            recommended_status,
            growth_info,
        ) = await self.growing_file_detector.check_file_growth_status(tracked_file)

        if recommended_status != tracked_file.status:
            await self.state_manager.update_file_status_by_id(
                file_id=tracked_file.id,
                status=recommended_status,
                file_size=metadata.size,
            )
            logging.info(
                f"GROWTH UPDATE: {file_path} -> {recommended_status} [UUID: {tracked_file.id[:8]}...]"
            )

    async def _handle_traditional_stability_logic(
            self, metadata: FileMetadata, tracked_file
    ) -> None:
        file_path = metadata.path.path

        if metadata.size != tracked_file.file_size:
            await self.state_manager.update_file_status_by_id(
                file_id=tracked_file.id,
                status=FileStatus.DISCOVERED,
                file_size=metadata.size,
            )
            logging.debug(
                f"SIZE UPDATE: {file_path} -> {metadata.size} bytes [UUID: {tracked_file.id[:8]}...]"
            )

        is_stable = await self.stability_tracker.check_file_stability(metadata)
        if is_stable:
            await self.state_manager.update_file_status_by_id(
                file_id=tracked_file.id,
                status=FileStatus.READY,
            )
            logging.info(
                f"STABLE: {file_path} -> READY [UUID: {tracked_file.id[:8]}...]"
            )
