import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Set
from typing import TYPE_CHECKING

import aiofiles.os

from app.config import Settings
from app.models import FileStatus, TrackedFile
from app.services.growing_file_detector import GrowingFileDetector
from app.services.state_manager import StateManager
from .domain_objects import ScanConfiguration

if TYPE_CHECKING:
    from app.services.storage_monitor import StorageMonitorService




@dataclass(frozen=True)
class FilePath:
    """Domain object representing a file path with its operations."""

    path: str

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def extension(self) -> str:
        return Path(self.path).suffix.lower()

    async def exists(self) -> bool:
        return await aiofiles.os.path.exists(self.path)

    def is_mxf_file(self) -> bool:
        return self.extension == ".mxf"

    def should_ignore(self) -> bool:
        """Check if file should be ignored (test files, etc.)"""
        return "test_file" in self.name.lower() or self.name.startswith(".")

    def __hash__(self) -> int:
        """Make FilePath hashable so it can be stored in sets."""
        return hash(self.path)

    def __eq__(self, other) -> bool:
        """Define equality based on path."""
        if not isinstance(other, FilePath):
            return False
        return self.path == other.path


@dataclass
class FileMetadata:
    """Domain object encapsulating file metadata and operations."""

    path: FilePath
    size: int
    last_write_time: datetime

    @classmethod
    async def from_path(cls, file_path: str) -> Optional["FileMetadata"]:
        """Create FileMetadata from a file path."""
        try:
            path_obj = FilePath(file_path)
            if not await path_obj.exists():
                return None

            stat_result = await aiofiles.os.stat(file_path)
            return cls(
                path=path_obj,
                size=stat_result.st_size,
                last_write_time=datetime.fromtimestamp(stat_result.st_mtime),
            )
        except (OSError, IOError):
            return None

    def is_empty(self) -> bool:
        return self.size == 0



class FileScanner:

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

        current_files = await self._discover_all_files()
        await self._cleanup_missing_files(current_files)

        # StateManager handles its own cleanup - no need for separate tracking cleanup
        await self._cleanup_old_files()

        current_files = await self._discover_all_files()
        await self._process_discovered_files(current_files)
        await self._check_file_stability()

        scan_duration = (datetime.now() - scan_start).total_seconds()
        logging.debug(f"Scan iteration completed in {scan_duration:.2f}s")

    async def _cleanup_missing_files(self, current_files: Set[FilePath]) -> int:
        """Clean up files that no longer exist in the source directory."""
        try:
            current_file_paths = {fp.path for fp in current_files}

            removed_count = await self.state_manager.cleanup_missing_files(
                current_file_paths
            )

            if removed_count > 0:
                logging.info(
                    f"Cleanup: Removed {removed_count} files that no longer exist"
                )

            return removed_count

        except Exception as e:
            logging.error(f"Error cleaning up missing files: {e}")
            return 0

    async def _cleanup_old_files(self) -> int:
        """Clean up old files from memory based on configured retention period."""
        try:
            removed_count = await self.state_manager.cleanup_old_files(
                max_age_hours=self.config.keep_files_hours,
            )

            if removed_count > 0:
                logging.info(
                    f"Cleanup: Removed {removed_count} old files from memory "
                    f"(older than {self.config.keep_files_hours} hours)"
                )

            return removed_count

        except Exception as e:
            logging.error(f"Error cleaning up old files: {e}")
            return 0

    async def _discover_all_files(self) -> Set[FilePath]:
        """Discover all MXF files in the source directory."""
        discovered_files: Set[FilePath] = set()

        try:
            source_path = Path(self.config.source_directory)

            if not await aiofiles.os.path.exists(source_path):
                logging.debug(f"Source directory does not exist: {source_path}")
                return discovered_files

            if not await aiofiles.os.path.isdir(source_path):
                logging.debug(f"Source path is not a directory: {source_path}")
                return discovered_files

            # Scan recursively for .mxf files
            for root, _, files in os.walk(source_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    abs_file_path = os.path.abspath(file_path)
                    path_obj = FilePath(abs_file_path)

                    if path_obj.is_mxf_file() and not path_obj.should_ignore():
                        discovered_files.add(path_obj)

            logging.debug(f"Discovered {len(discovered_files)} MXF files")

        except Exception as e:
            logging.error(f"Error discovering files: {e}")

        return discovered_files

    async def _process_discovered_files(self, current_files: Set[FilePath]) -> None:
        for file_path_obj in current_files:
            try:
                file_path = file_path_obj.path

                # Check if file should be skipped due to cooldown or other conditions
                should_skip = await self.state_manager.should_skip_file_processing(file_path)
                if should_skip:
                    continue

                # Brug get_active_file_by_path i stedet for get_file_by_path
                # Dette sikrer at completed files ikke bliver genbrugt når en ny fil 
                # med samme navn bliver opdaget
                existing_file = await self.state_manager.get_active_file_by_path(file_path)
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

                # File tracking is now handled entirely by StateManager
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

        await self.growing_file_detector.update_file_growth_info(tracked_file, metadata.size)

        recommended_status, growth_info = await self.growing_file_detector.check_file_growth_status(tracked_file)

        if recommended_status != tracked_file.status:
            # Don't override WAITING_FOR_NETWORK status from growth checks
            if tracked_file.status == FileStatus.WAITING_FOR_NETWORK:
                logging.debug(f"Preserving WAITING_FOR_NETWORK status for {file_path}")
                return
                
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

        # Check if file has changed and update metadata if needed
        file_changed = await self.state_manager.update_file_metadata(
            tracked_file.id, metadata.size, metadata.last_write_time
        )

        if file_changed:
            # File changed, status reset to DISCOVERED and stability timer reset
            await self.state_manager.update_file_status_by_id(
                file_id=tracked_file.id,
                status=FileStatus.DISCOVERED,
            )
            logging.debug(
                f"SIZE/TIME UPDATE: {file_path} -> {metadata.size} bytes [UUID: {tracked_file.id[:8]}...]"
            )
            return  # Don't check stability if file just changed

        # Check if file is stable using StateManager
        is_stable = await self.state_manager.is_file_stable(
            tracked_file.id, self.config.file_stable_time_seconds
        )
        
        if is_stable:
            await self.state_manager.update_file_status_by_id(
                file_id=tracked_file.id,
                status=FileStatus.READY,
            )
            logging.info(
                f"STABLE: {file_path} -> READY [UUID: {tracked_file.id[:8]}...]"
            )
