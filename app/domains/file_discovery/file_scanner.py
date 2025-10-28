import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Set, Dict, Any
from typing import TYPE_CHECKING

import aiofiles.os

from app.config import Settings
from app.core.events.event_bus import DomainEventBus
from app.models import FileStatus, TrackedFile
from app.core.cqrs.command_bus import CommandBus
from app.core.cqrs.query_bus import QueryBus
from .domain_objects import ScanConfiguration
from .commands import AddFileCommand, MarkFileStableCommand, MarkFileGrowingCommand, MarkFileReadyToStartGrowingCommand
from .queries import ShouldSkipFileProcessingQuery, GetActiveFileByPathQuery, GetFilesByStatusQuery
from .growing_file_detector import GrowingFileDetector

if TYPE_CHECKING:
    from app.services.storage_monitor import StorageMonitorService


async def get_file_metadata(file_path: str) -> Optional[Dict[str, Any]]:
    """Get file metadata including size and modification time."""
    try:
        path = Path(file_path)
        if not await aiofiles.os.path.exists(path):
            return None

        stat_result = await aiofiles.os.stat(file_path)
        return {
            "path": path,
            "size": stat_result.st_size,
            "last_write_time": datetime.fromtimestamp(stat_result.st_mtime),
        }
    except (OSError, IOError):
        return None


def is_mxf_file(path: Path) -> bool:
    """Check if file is an MXF file."""
    return path.suffix.lower() == ".mxf"


def should_ignore_file(path: Path) -> bool:
    """Check if file should be ignored (test files, etc.)"""
    return "test_file" in path.name.lower() or path.name.startswith(".")


class FileScanner:
    def __init__(
        self,
        config: ScanConfiguration,
        command_bus: CommandBus,
        query_bus: QueryBus,
        storage_monitor: Optional["StorageMonitorService"] = None,
        settings: Optional[Settings] = None,
        event_bus: Optional[DomainEventBus] = None,
    ):
        self.config = config
        self._command_bus = command_bus
        self._query_bus = query_bus
        self.storage_monitor = storage_monitor
        self.settings = settings
        self._event_bus = event_bus
        self._running = False
        self._scan_task: Optional[asyncio.Task] = None

        # Initialize GrowingFileDetector with CQRS
        self.growing_file_detector = GrowingFileDetector(
            settings=settings,
            command_bus=command_bus,
            query_bus=query_bus
        )

        logging.info("FileScanner initialized with CQRS architecture")

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

        # Start growing file detector monitoring
        await self.growing_file_detector.start_monitoring()

        # Start scanning loop as background task instead of blocking
        self._scan_task = asyncio.create_task(self._scan_folder_loop())

        # Return immediately - don't wait for the task to complete
        logging.info("Scanner task started in background")

    async def stop_scanning(self) -> None:
        if not self._running:
            logging.warning("Scanner is not running")
            return

        self._running = False
        logging.info("File Scanner stop requested")

        # Cancel and cleanup scan task
        if self._scan_task and not self._scan_task.done():
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                logging.debug("Scanner task cancelled successfully")
            except Exception as e:
                logging.error(f"Error during scanner task cancellation: {e}")

        # Stop growing file detector monitoring
        await self.growing_file_detector.stop_monitoring()

        self._scan_task = None
        logging.info("File Scanner stopped")

    async def _scan_folder_loop(self) -> None:
        try:
            while self._running:
                try:
                    await self._execute_scan_iteration()
                    await asyncio.sleep(self.config.polling_interval_seconds)
                except asyncio.CancelledError:
                    logging.info("Scanner loop cancelled")
                    break
                except Exception as e:
                    logging.error(f"Error in scan iteration: {e}")
                    await asyncio.sleep(5)
        finally:
            # Cleanup when loop exits
            await self.growing_file_detector.stop_monitoring()
            self._running = False
            logging.info("Scanner loop completed")

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

    async def _cleanup_missing_files(self, current_files: Set[Path]) -> int:
        """Clean up files that no longer exist in the source directory."""
        try:
            current_file_paths = {str(path) for path in current_files}

            # TODO: Implement via CQRS - CleanupMissingFilesCommand
            # For now, skip this functionality until we create the command
            logging.debug(f"Cleanup missing files - found {len(current_file_paths)} current files")
            return 0

        except Exception as e:
            logging.error(f"Error cleaning up missing files: {e}")
            return 0

    async def _cleanup_old_files(self) -> int:
        """Clean up old files from memory based on configured retention period."""
        try:
            # TODO: Implement via CQRS - CleanupOldFilesCommand
            # For now, skip this functionality until we create the command
            logging.debug(f"Cleanup old files - max age: {self.config.keep_files_hours} hours")
            return 0

        except Exception as e:
            logging.error(f"Error cleaning up old files: {e}")
            return 0

    async def _discover_all_files(self) -> Set[Path]:
        """Discover all MXF files in the source directory."""
        discovered_files: Set[Path] = set()

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
                    path_obj = Path(abs_file_path)

                    if is_mxf_file(path_obj) and not should_ignore_file(path_obj):
                        discovered_files.add(path_obj)

            logging.debug(f"Discovered {len(discovered_files)} MXF files")

        except Exception as e:
            logging.error(f"Error discovering files: {e}")

        return discovered_files

    async def _process_discovered_files(self, current_files: Set[Path]) -> None:
        for path_obj in current_files:
            try:
                file_path = str(path_obj)

                # Use CQRS query to check if we should skip processing
                query = ShouldSkipFileProcessingQuery(file_path=file_path)
                should_skip = await self._query_bus.execute(query)
                if should_skip:
                    continue

                # Use CQRS query to get existing file
                existing_file_query = GetActiveFileByPathQuery(file_path=file_path)
                existing_file = await self._query_bus.execute(existing_file_query)
                if existing_file is not None:
                    await self._check_existing_file_changes(existing_file, file_path)
                    continue

                metadata = await get_file_metadata(file_path)
                if metadata is None:
                    continue

                if metadata["size"] == 0:  # Check if empty
                    logging.debug(f"Skipping empty file: {path_obj.name}")
                    continue

                # Use CQRS command to add file
                command = AddFileCommand(
                    file_path=file_path,
                    file_size=metadata["size"],
                    last_write_time=metadata["last_write_time"]
                )
                await self._command_bus.execute(command)
                logging.info(
                    f"NEW FILE EVENT: {path_obj.name} ({metadata['size']} bytes)"
                )

            except Exception as e:
                logging.error(f"Error processing file {path_obj}: {e}")

    async def _check_existing_file_changes(self, tracked_file, file_path: str) -> None:
        metadata = await get_file_metadata(file_path)
        if metadata is None:
            return

        if metadata["size"] != tracked_file.file_size:
            logging.info(
                f"SIZE CHANGE: {tracked_file.file_path} "
                f"({tracked_file.file_size} → {metadata['size']} bytes) "
                f"[UUID: {tracked_file.id[:8]}...]"
            )

            # TODO: Implement UpdateFileCommand via CQRS
            # For now, just log the change
            logging.debug(f"File size change detected for {file_path}")

    async def _check_file_stability(self) -> None:
        try:
            # Use CQRS queries to get files by status
            discovered_query = GetFilesByStatusQuery(status=FileStatus.DISCOVERED)
            discovered_files = await self._query_bus.execute(discovered_query)
            
            growing_query = GetFilesByStatusQuery(status=FileStatus.GROWING)
            growing_files = await self._query_bus.execute(growing_query)

            all_files_to_check = discovered_files + growing_files

            for tracked_file in all_files_to_check:
                file_path = tracked_file.file_path

                metadata = await get_file_metadata(file_path)
                if metadata is None:
                    continue

                # Use GrowingFileDetector to check file growth status
                recommended_status = await self.growing_file_detector.check_file_growth_status(tracked_file)
                
                if recommended_status != tracked_file.status:
                    # File status changed based on growth analysis
                    if recommended_status == FileStatus.READY:
                        command = MarkFileStableCommand(
                            file_id=tracked_file.id,
                            file_path=file_path
                        )
                        await self._command_bus.execute(command)
                        logging.info(
                            f"STABILITY UPDATE: {file_path} -> READY [UUID: {tracked_file.id[:8]}...]"
                        )
                    elif recommended_status == FileStatus.GROWING:
                        command = MarkFileGrowingCommand(
                            file_id=tracked_file.id,
                            file_path=tracked_file.file_path
                        )
                        await self._command_bus.execute(command)
                        logging.info(
                            f"GROWING UPDATE: {file_path} -> GROWING [UUID: {tracked_file.id[:8]}...]"
                        )
                    elif recommended_status == FileStatus.READY_TO_START_GROWING:
                        command = MarkFileReadyToStartGrowingCommand(
                            file_id=tracked_file.id,
                            file_path=tracked_file.file_path
                        )
                        await self._command_bus.execute(command)
                        logging.info(
                            f"GROWING UPDATE: {file_path} -> READY_TO_START_GROWING [UUID: {tracked_file.id[:8]}...]"
                        )

        except Exception as e:
            logging.error(f"Error in stability check: {e}")
