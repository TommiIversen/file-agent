"""
Growing File Detector Service

Detects and monitors files that are actively growing (being written to).
Used to identify MXF video files and other large files that should start
copying before they are completely written.
"""

import asyncio
import os
from datetime import datetime
from typing import Dict, Optional, Tuple
from dataclasses import dataclass



from app.config import Settings
from app.models import FileStatus, TrackedFile
from app.services.state_manager import StateManager
import logging


@dataclass
class FileGrowthInfo:
    """Information about a file's growth pattern"""

    current_size: int
    last_size: int
    last_check_time: datetime
    first_seen_size: int
    first_seen_time: datetime
    stable_since: Optional[datetime] = None

    @property
    def growth_rate_mbps(self) -> float:
        """Calculate growth rate in MB per second"""
        if self.last_check_time == self.first_seen_time:
            return 0.0

        time_diff = (self.last_check_time - self.first_seen_time).total_seconds()
        if time_diff <= 0:
            return 0.0

        size_diff = self.current_size - self.first_seen_size
        return (size_diff / (1024 * 1024)) / time_diff

    @property
    def is_growing(self) -> bool:
        """Check if file is currently growing"""
        return self.current_size > self.last_size

    @property
    def size_mb(self) -> float:
        """Current file size in MB"""
        return self.current_size / (1024 * 1024)


class GrowingFileDetector:
    """
    Detects and monitors growing files for streaming copy capability.

    Tracks file sizes over time to identify files that are actively being written
    and determines when they're ready to start growing copy operations.
    """

    def __init__(self, settings: Settings, state_manager: StateManager):
        self.settings = settings
        self.state_manager = state_manager

        # File growth tracking
        self._growth_tracking: Dict[str, FileGrowthInfo] = {}  # use TrackedFile.is as key
        self._monitoring_active = False

        # Configuration shortcuts
        self.min_size_bytes = settings.growing_file_min_size_mb * 1024 * 1024
        self.poll_interval = settings.growing_file_poll_interval_seconds
        self.growth_timeout = settings.growing_file_growth_timeout_seconds

        logging.info(
            f"GrowingFileDetector initialized - min_size: {settings.growing_file_min_size_mb}MB, "
            f"poll_interval: {self.poll_interval}s, timeout: {self.growth_timeout}s"
        )

    async def start_monitoring(self):
        """Start the background monitoring task"""
        if self._monitoring_active:
            logging.warning("Growing file monitoring already active")
            return

        self._monitoring_active = True
        logging.info("Starting growing file monitoring")

        # Start background monitoring task
        asyncio.create_task(self._monitor_growing_files_loop())

    async def stop_monitoring(self):
        """Stop the background monitoring"""
        self._monitoring_active = False
        logging.info("Stopping growing file monitoring")

    async def check_file_growth_status(
        self, tracked_file: TrackedFile
    ) -> Tuple[FileStatus, Optional[FileGrowthInfo]]:

        try:
            # Get current file info
            if not os.path.exists(tracked_file.file_path):
                return FileStatus.FAILED, None

            current_size = os.path.getsize(tracked_file.file_path)
            current_time = datetime.now()

            # Get or create growth tracking info
            if tracked_file.id not in self._growth_tracking:
                self._growth_tracking[tracked_file.id] = FileGrowthInfo(
                    current_size=current_size,
                    last_size=current_size,
                    last_check_time=current_time,
                    first_seen_size=current_size,
                    first_seen_time=current_time,
                )
                logging.debug(
                    f"Started tracking growth for {tracked_file.file_path} (size: {current_size / 1024 / 1024:.1f}MB)"
                )
                return FileStatus.DISCOVERED, self._growth_tracking[tracked_file.id]

            # Update growth info (but save last_size before updating)
            growth_info = self._growth_tracking[tracked_file.id]
            previous_size = growth_info.current_size
            growth_info.last_size = previous_size  # Keep track of previous size
            growth_info.current_size = current_size
            growth_info.last_check_time = current_time

            # Check if file is growing (compare current with previous)
            is_currently_growing = current_size > previous_size
            has_grown = growth_info.current_size > growth_info.first_seen_size

            if is_currently_growing:
                # File is actively growing
                growth_info.stable_since = None

                # Check if it's large enough for growing copy
                if current_size >= self.min_size_bytes:
                    logging.debug(
                        f"File {tracked_file.file_path} ready for growing copy "
                        f"(size: {growth_info.size_mb:.1f}MB, rate: {growth_info.growth_rate_mbps:.2f}MB/s)"
                    )
                    return FileStatus.READY_TO_START_GROWING, growth_info
                else:
                    logging.debug(
                        f"File {tracked_file.file_path} still growing but too small "
                        f"(size: {growth_info.size_mb:.1f}MB < {self.settings.growing_file_min_size_mb}MB)"
                    )
                    return FileStatus.GROWING, growth_info
            else:
                # File is not currently growing

                # If file never grew and is still small, it's just a normal static file
                if not has_grown and current_size < self.min_size_bytes:
                    # Static small file - check if it's stable for normal copy
                    if growth_info.stable_since is None:
                        growth_info.stable_since = current_time

                    stable_duration = (
                        current_time - growth_info.stable_since
                    ).total_seconds()
                    if stable_duration >= self.growth_timeout:
                        logging.debug(
                            f"File {tracked_file.file_path} is static and stable, ready for normal copy "
                            f"(size: {growth_info.size_mb:.1f}MB)"
                        )
                        return FileStatus.READY, growth_info
                    else:
                        logging.debug(
                            f"File {tracked_file.file_path} checking stability for normal copy "
                            f"({stable_duration:.1f}s/{self.growth_timeout}s)"
                        )
                        return FileStatus.DISCOVERED, growth_info

                # File either grew before OR is large - check stability for growing copy
                if growth_info.stable_since is None:
                    growth_info.stable_since = current_time

                stable_duration = (
                    current_time - growth_info.stable_since
                ).total_seconds()

                if stable_duration >= self.growth_timeout:
                    # File is stable - decide between normal copy or growing copy
                    if has_grown and current_size >= self.min_size_bytes:
                        # File grew in the past and is now stable and large enough - use growing copy
                        logging.debug(
                            f"File {tracked_file.file_path} finished growing, ready for growing copy "
                            f"(size: {growth_info.size_mb:.1f}MB)"
                        )
                        return FileStatus.READY_TO_START_GROWING, growth_info
                    else:
                        # File never grew or is too small - use normal copy
                        logging.debug(
                            f"File {tracked_file.file_path} is stable, ready for normal copy "
                            f"(size: {growth_info.size_mb:.1f}MB)"
                        )
                        return FileStatus.READY, growth_info
                else:
                    # Still in stability check period - use GROWING if it has grown, DISCOVERED if not
                    if has_grown:
                        logging.debug(
                            f"File {tracked_file.file_path} previously grew, checking post-growth stability "
                            f"({stable_duration:.1f}s/{self.growth_timeout}s)"
                        )
                        return FileStatus.GROWING, growth_info
                    else:
                        logging.debug(
                            f"File {tracked_file.file_path} checking initial stability "
                            f"({stable_duration:.1f}s/{self.growth_timeout}s)"
                        )
                        return FileStatus.DISCOVERED, growth_info

        except Exception as e:
            logging.error(f"Error checking growth status for {tracked_file.file_path}: {e}")
            return FileStatus.FAILED, None

    async def update_file_growth_info(self, tracked_file: TrackedFile, new_size: int) -> None:
        """
        Update growth tracking info when we get external size updates.

        This is called by FileScannerService when it detects size changes.
        """
        current_time = datetime.now()

        if tracked_file.id not in self._growth_tracking:
            self._growth_tracking[tracked_file.id] = FileGrowthInfo(
                current_size=new_size,
                last_size=new_size,
                last_check_time=current_time,
                first_seen_size=new_size,
                first_seen_time=current_time,
            )
        else:
            growth_info = self._growth_tracking[tracked_file.id]
            growth_info.last_size = growth_info.current_size
            growth_info.current_size = new_size
            growth_info.last_check_time = current_time

            # Reset stability timer if file grew
            if new_size > growth_info.last_size:
                growth_info.stable_since = None

    async def _cleanup_tracking(self, tracked_file_id: str) -> None:
        """Remove growth tracking for a completed/failed file"""
        if tracked_file_id in self._growth_tracking:
            del self._growth_tracking[tracked_file_id]
            logging.debug(f"Cleaned up growth tracking for {tracked_file_id}")

    async def _monitor_growing_files_loop(self):
        """Background loop to monitor all tracked growing files"""
        logging.info("Starting growing file monitoring loop")

        while self._monitoring_active:
            try:
                # Get all files currently being tracked for growth
                tracked_file_id_to_check = list(self._growth_tracking.keys())

                for tracked_file_id in tracked_file_id_to_check:
                    if not self._monitoring_active:
                        break

                    try:
                        # Get current tracked file from state manager
                        tracked_file = await self.state_manager.get_file_by_id(tracked_file_id)
                        if not tracked_file:
                            # File no longer tracked, clean up
                            await self._cleanup_tracking(tracked_file_id)
                            continue

                        # Skip files that are already in copy phase
                        if tracked_file.status in [
                            FileStatus.IN_QUEUE,
                            FileStatus.COPYING,
                            FileStatus.GROWING_COPY,
                            FileStatus.COMPLETED,
                            FileStatus.FAILED,
                        ]:
                            continue

                        # Check growth status
                        (
                            recommended_status,
                            growth_info,
                        ) = await self.check_file_growth_status(tracked_file)

                        # Update file status if it changed - USE UUID for precision!
                        if recommended_status != tracked_file.status:
                            update_kwargs = {}

                            if growth_info:
                                update_kwargs.update(
                                    {
                                        "is_growing_file": recommended_status
                                        in [
                                            FileStatus.GROWING,
                                            FileStatus.READY_TO_START_GROWING,
                                        ],
                                        "growth_rate_mbps": growth_info.growth_rate_mbps,
                                        "file_size": growth_info.current_size,
                                        "last_growth_check": datetime.now(),
                                    }
                                )

                            # Use UUID-based update for precise file reference
                            await self.state_manager.update_file_status_by_id(
                                file_id=tracked_file.id,  # Precise UUID reference
                                status=recommended_status, 
                                **update_kwargs
                            )
                            logging.debug(f"GROWING UPDATE: {tracked_file.file_path} -> {recommended_status} [UUID: {tracked_file.id[:8]}...]")

                    except Exception as e:
                        logging.error(f"Error monitoring growth for {tracked_file_id}: {e}")

                # Wait before next check
                await asyncio.sleep(self.poll_interval)

            except Exception as e:
                logging.error(f"Error in growing file monitoring loop: {e}")
                await asyncio.sleep(self.poll_interval)

        logging.info("Growing file monitoring loop stopped")
