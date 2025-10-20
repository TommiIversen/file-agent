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
    current_size: int
    last_size: int
    last_check_time: datetime
    first_seen_size: int
    first_seen_time: datetime
    stable_since: Optional[datetime] = None

    @property
    def growth_rate_mbps(self) -> float:
        if self.last_check_time == self.first_seen_time:
            return 0.0

        time_diff = (self.last_check_time - self.first_seen_time).total_seconds()
        if time_diff <= 0:
            return 0.0

        size_diff = self.current_size - self.first_seen_size
        return (size_diff / (1024 * 1024)) / time_diff

    @property
    def is_growing(self) -> bool:
        return self.current_size > self.last_size

    @property
    def size_mb(self) -> float:
        return self.current_size / (1024 * 1024)


class GrowingFileDetector:
    def __init__(self, settings: Settings, state_manager: StateManager):
        self.settings = settings
        self.state_manager = state_manager

        self._growth_tracking: Dict[str, FileGrowthInfo] = {}
        self._monitoring_active = False
        self.min_size_bytes = settings.growing_file_min_size_mb * 1024 * 1024
        self.poll_interval = settings.growing_file_poll_interval_seconds
        self.growth_timeout = settings.growing_file_growth_timeout_seconds

        logging.info(
            f"GrowingFileDetector initialized - min_size: {settings.growing_file_min_size_mb}MB, "
            f"poll_interval: {self.poll_interval}s, timeout: {self.growth_timeout}s"
        )

    async def start_monitoring(self):
        if self._monitoring_active:
            logging.warning("Growing file monitoring already active")
            return

        self._monitoring_active = True
        logging.info("Starting growing file monitoring")

        asyncio.create_task(self._monitor_growing_files_loop())

    async def stop_monitoring(self):
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

            growth_info = self._growth_tracking[tracked_file.id]
            previous_size = growth_info.current_size
            growth_info.last_size = previous_size
            growth_info.current_size = current_size
            growth_info.last_check_time = current_time

            is_currently_growing = current_size > previous_size
            has_grown = growth_info.current_size > growth_info.first_seen_size

            if is_currently_growing:
                growth_info.stable_since = None

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
                if not has_grown and current_size < self.min_size_bytes:
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

                if growth_info.stable_since is None:
                    growth_info.stable_since = current_time

                stable_duration = (
                    current_time - growth_info.stable_since
                ).total_seconds()

                if stable_duration >= self.growth_timeout:
                    if has_grown and current_size >= self.min_size_bytes:
                        logging.debug(
                            f"File {tracked_file.file_path} finished growing, ready for growing copy "
                            f"(size: {growth_info.size_mb:.1f}MB)"
                        )
                        return FileStatus.READY_TO_START_GROWING, growth_info
                    else:
                        logging.debug(
                            f"File {tracked_file.file_path} is stable, ready for normal copy "
                            f"(size: {growth_info.size_mb:.1f}MB)"
                        )
                        return FileStatus.READY, growth_info
                else:
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
            logging.error(
                f"Error checking growth status for {tracked_file.file_path}: {e}"
            )
            return FileStatus.FAILED, None

    async def update_file_growth_info(
        self, tracked_file: TrackedFile, new_size: int
    ) -> None:
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

            if new_size > growth_info.last_size:
                growth_info.stable_since = None

    async def _cleanup_tracking(self, tracked_file_id: str) -> None:
        if tracked_file_id in self._growth_tracking:
            del self._growth_tracking[tracked_file_id]
            logging.debug(f"Cleaned up growth tracking for {tracked_file_id}")

    async def _monitor_growing_files_loop(self):
        logging.info("Starting growing file monitoring loop")

        while self._monitoring_active:
            try:
                tracked_file_id_to_check = list(self._growth_tracking.keys())

                for tracked_file_id in tracked_file_id_to_check:
                    if not self._monitoring_active:
                        break

                    try:
                        tracked_file = await self.state_manager.get_file_by_id(
                            tracked_file_id
                        )
                        if not tracked_file:
                            await self._cleanup_tracking(tracked_file_id)
                            continue

                        if tracked_file.status in [
                            FileStatus.IN_QUEUE,
                            FileStatus.COPYING,
                            FileStatus.GROWING_COPY,
                            FileStatus.COMPLETED,
                            FileStatus.FAILED,
                        ]:
                            continue

                        (
                            recommended_status,
                            growth_info,
                        ) = await self.check_file_growth_status(tracked_file)

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

                            await self.state_manager.update_file_status_by_id(
                                file_id=tracked_file.id,
                                status=recommended_status,
                                **update_kwargs,
                            )
                            logging.debug(
                                f"GROWING UPDATE: {tracked_file.file_path} -> {recommended_status} [UUID: {tracked_file.id[:8]}...]"
                            )

                    except Exception as e:
                        logging.error(
                            f"Error monitoring growth for {tracked_file_id}: {e}"
                        )

                await asyncio.sleep(self.poll_interval)

            except Exception as e:
                logging.error(f"Error in growing file monitoring loop: {e}")
                await asyncio.sleep(self.poll_interval)

        logging.info("Growing file monitoring loop stopped")
