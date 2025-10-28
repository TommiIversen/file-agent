import logging
from datetime import datetime

import aiofiles.os

from app.config import Settings
from app.models import FileStatus, TrackedFile
from app.core.cqrs.command_bus import CommandBus
from app.core.cqrs.query_bus import QueryBus
from .commands import UpdateFileGrowthInfoCommand


class GrowingFileDetector:
    def __init__(
        self, 
        settings: Settings, 
        command_bus: CommandBus,
        query_bus: QueryBus
    ):
        self.settings = settings
        self._command_bus = command_bus
        self._query_bus = query_bus

        # Removed _growth_tracking - using CQRS as single source of truth
        self._monitoring_active = False
        self.min_size_bytes = settings.growing_file_min_size_mb * 1024 * 1024
        self.poll_interval = settings.growing_file_poll_interval_seconds
        self.growth_timeout = settings.growing_file_growth_timeout_seconds

        logging.info(
            f"GrowingFileDetector initialized with CQRS - min_size: {settings.growing_file_min_size_mb}MB, "
            f"poll_interval: {self.poll_interval}s, timeout: {self.growth_timeout}s"
        )

    async def start_monitoring(self):
        if self._monitoring_active:
            logging.warning("Growing file monitoring already active")
            return

        self._monitoring_active = True
        logging.info("Starting growing file monitoring")

        # The monitoring loop is disabled because the FileScanner now drives the growth checks.
        # asyncio.create_task(self._monitor_growing_files_loop())

    async def stop_monitoring(self):
        self._monitoring_active = False
        logging.info("Stopping growing file monitoring")

    async def check_file_growth_status(self, tracked_file: TrackedFile) -> FileStatus:
        """
        Check file growth status using TrackedFile state instead of separate tracking.
        Returns the recommended FileStatus.
        """
        # CRITICAL: Don't modify files that are waiting for network
        # This prevents the bounce loop between READY and WAITING_FOR_NETWORK
        if tracked_file.status == FileStatus.WAITING_FOR_NETWORK:
            logging.debug(
                f"Skipping growth check for {tracked_file.file_path} - waiting for network"
            )
            return tracked_file.status

        # CRITICAL: Don't modify files that are in copy processing
        # This prevents loops between copy system and growing file detector
        if tracked_file.status in [
            FileStatus.IN_QUEUE,
            FileStatus.COPYING,
            FileStatus.GROWING_COPY,
            FileStatus.COMPLETED,
            FileStatus.FAILED,
            FileStatus.REMOVED,
            FileStatus.SPACE_ERROR,
        ]:
            logging.debug(
                f"Skipping growth check for {tracked_file.file_path} - in copy processing or terminal state"
            )
            return tracked_file.status

        try:
            current_size = await aiofiles.os.path.getsize(tracked_file.file_path)
            current_time = datetime.now()

            if tracked_file.last_growth_check is None:
                # First check
                command = UpdateFileGrowthInfoCommand(
                    file_id=tracked_file.id,
                    file_size=current_size,
                    previous_file_size=current_size,
                    growth_stable_since=current_time,
                    last_growth_check=current_time,
                )
                await self._command_bus.execute(command)
                return FileStatus.DISCOVERED

            if current_size != tracked_file.file_size:
                # File is growing
                command = UpdateFileGrowthInfoCommand(
                    file_id=tracked_file.id,
                    file_size=current_size,
                    previous_file_size=tracked_file.file_size,
                    growth_stable_since=None,  # Reset stability timer
                    last_growth_check=current_time,
                )
                await self._command_bus.execute(command)
                if current_size >= self.min_size_bytes:
                    return FileStatus.READY_TO_START_GROWING
                else:
                    return FileStatus.GROWING
            else:
                # File is not growing
                if tracked_file.growth_stable_since is None:
                    # Just stopped growing, start stability timer
                    command = UpdateFileGrowthInfoCommand(
                        file_id=tracked_file.id,
                        growth_stable_since=current_time,
                        last_growth_check=current_time,
                    )
                    await self._command_bus.execute(command)
                    return tracked_file.status

                stable_duration = (current_time - tracked_file.growth_stable_since).total_seconds()
                if stable_duration >= self.growth_timeout:
                    # File is stable
                    return FileStatus.READY
                else:
                    # Not stable long enough
                    return tracked_file.status

        except FileNotFoundError:
            return FileStatus.REMOVED
        except Exception as e:
            logging.error(f"Error checking growth status for {tracked_file.file_path}: {e}")
            return FileStatus.FAILED

    async def update_file_growth_info(
        self, tracked_file: TrackedFile, new_size: int
    ) -> None:
        """Update file growth information using CQRS instead of separate tracking."""
        current_time = datetime.now()

        # Calculate growth rate if we have previous data
        growth_rate = tracked_file.growth_rate_mbps
        if tracked_file.last_growth_check and tracked_file.first_seen_size > 0:
            time_diff = (current_time - tracked_file.last_growth_check).total_seconds()
            if time_diff > 0:
                size_diff = new_size - tracked_file.first_seen_size
                growth_rate = (size_diff / (1024 * 1024)) / time_diff

        # Determine if growth has stopped
        growth_stable_since = tracked_file.growth_stable_since
        if new_size > tracked_file.file_size:
            # File is still growing
            growth_stable_since = None
        elif growth_stable_since is None:
            # File stopped growing, mark the time
            growth_stable_since = current_time

        # NOTE: PAUSED file checks removed in fail-and-rediscover strategy
        # Files now fail immediately instead of pausing during network issues

        # Update TrackedFile with new growth information via CQRS
        command = UpdateFileGrowthInfoCommand(
            file_id=tracked_file.id,
            file_size=new_size,
            previous_file_size=tracked_file.file_size,
            growth_rate_mbps=growth_rate,
            growth_stable_since=growth_stable_since,
            last_growth_check=current_time
        )
        await self._command_bus.execute(command)

