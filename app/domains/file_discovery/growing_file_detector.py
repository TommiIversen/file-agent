import asyncio
import logging
from datetime import datetime
from typing import Optional, Tuple

import aiofiles.os

from app.config import Settings
from app.models import FileStatus, TrackedFile
from app.core.cqrs.command_bus import CommandBus
from app.core.cqrs.query_bus import QueryBus
from .commands import UpdateFileGrowthInfoCommand, MarkFileGrowingCommand, MarkFileReadyToStartGrowingCommand
from .queries import GetFilesNeedingGrowthMonitoringQuery


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

        asyncio.create_task(self._monitor_growing_files_loop())

    async def stop_monitoring(self):
        self._monitoring_active = False
        logging.info("Stopping growing file monitoring")

    async def check_file_growth_status(
        self, tracked_file: TrackedFile
    ) -> Tuple[FileStatus, Optional[TrackedFile]]:
        """
        Check file growth status using TrackedFile state instead of separate tracking.
        Returns updated TrackedFile with growth information.
        """
        # CRITICAL: Don't modify files that are waiting for network
        # This prevents the bounce loop between READY and WAITING_FOR_NETWORK
        if tracked_file.status == FileStatus.WAITING_FOR_NETWORK:
            logging.debug(
                f"Skipping growth check for {tracked_file.file_path} - waiting for network"
            )
            return tracked_file.status, tracked_file

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
            return tracked_file.status, tracked_file

        try:
            # Get current file info
            if not await aiofiles.os.path.exists(tracked_file.file_path):
                logging.info(
                    f"File no longer exists during growth check: {tracked_file.file_path}"
                )
                return FileStatus.REMOVED, None

            current_size = await aiofiles.os.path.getsize(tracked_file.file_path)
            current_time = datetime.now()

            # Initialize growth tracking fields if this is first check
            if tracked_file.last_growth_check is None:
                # First time seeing this file - initialize growth tracking
                command = UpdateFileGrowthInfoCommand(
                    file_id=tracked_file.id,
                    file_size=current_size,
                    previous_file_size=current_size,
                    growth_rate_mbps=0.0,
                    growth_stable_since=current_time,
                    last_growth_check=current_time
                )
                await self._command_bus.execute(command)

                # Create updated file object for return
                updated_file = TrackedFile(
                    id=tracked_file.id,
                    file_path=tracked_file.file_path,
                    file_size=current_size,
                    status=FileStatus.DISCOVERED,
                    discovered_at=tracked_file.discovered_at,
                    previous_file_size=current_size,
                    first_seen_size=current_size,  # Set first_seen_size to current size
                    last_growth_check=current_time,
                    growth_stable_since=current_time,
                    growth_rate_mbps=0.0
                )

                logging.debug(
                    f"Started tracking growth for {tracked_file.file_path} (size: {current_size / 1024 / 1024:.1f}MB)"
                )
                return FileStatus.DISCOVERED, updated_file

            # Update file with current size and time
            previous_size = tracked_file.file_size

            # Calculate growth rate
            time_diff = (current_time - tracked_file.last_growth_check).total_seconds()
            if time_diff > 0:
                size_diff = current_size - tracked_file.first_seen_size
                growth_rate = (
                    (size_diff / (1024 * 1024)) / time_diff if time_diff > 0 else 0.0
                )
            else:
                growth_rate = tracked_file.growth_rate_mbps

            is_currently_growing = current_size > previous_size
            has_grown = current_size > tracked_file.first_seen_size

            # Update growth stable timestamp
            growth_stable_since = tracked_file.growth_stable_since
            if is_currently_growing:
                growth_stable_since = None
            elif growth_stable_since is None:
                growth_stable_since = current_time

            # NOTE: PAUSED status checks removed in fail-and-rediscover strategy
            # Files now fail immediately instead of pausing during network issues

            # Update TrackedFile with new information via CQRS
            command = UpdateFileGrowthInfoCommand(
                file_id=tracked_file.id,
                file_size=current_size,
                previous_file_size=previous_size,
                growth_rate_mbps=growth_rate,
                growth_stable_since=growth_stable_since,
                last_growth_check=current_time
            )
            await self._command_bus.execute(command)

            # Create updated file object for decision logic
            updated_file = TrackedFile(
                id=tracked_file.id,
                file_path=tracked_file.file_path,
                file_size=current_size,
                status=tracked_file.status,
                discovered_at=tracked_file.discovered_at,
                previous_file_size=previous_size,
                first_seen_size=tracked_file.first_seen_size or current_size,
                last_growth_check=current_time,
                growth_stable_since=growth_stable_since,
                growth_rate_mbps=growth_rate
            )

            # Decision logic based on growth status
            if is_currently_growing:
                if current_size >= self.min_size_bytes:
                    logging.debug(
                        f"File {tracked_file.file_path} ready for growing copy "
                        f"(size: {current_size / 1024 / 1024:.1f}MB, rate: {growth_rate:.2f}MB/s)"
                    )
                    return FileStatus.READY_TO_START_GROWING, updated_file
                else:
                    logging.debug(
                        f"File {tracked_file.file_path} still growing but too small "
                        f"(size: {current_size / 1024 / 1024:.1f}MB < {self.settings.growing_file_min_size_mb}MB)"
                    )
                    return FileStatus.GROWING, updated_file
            else:
                # File is not currently growing
                if not has_grown and current_size < self.min_size_bytes:
                    # Small file that never grew
                    stable_duration = (
                        (current_time - growth_stable_since).total_seconds()
                        if growth_stable_since
                        else 0
                    )

                    if stable_duration >= self.growth_timeout:
                        logging.debug(
                            f"File {tracked_file.file_path} is static and stable, ready for normal copy "
                            f"(size: {current_size / 1024 / 1024:.1f}MB)"
                        )
                        return FileStatus.READY, updated_file
                    else:
                        logging.debug(
                            f"File {tracked_file.file_path} checking stability for normal copy "
                            f"({stable_duration:.1f}s/{self.growth_timeout}s)"
                        )
                        return FileStatus.DISCOVERED, updated_file

                # File has grown or is large enough
                stable_duration = (
                    (current_time - growth_stable_since).total_seconds()
                    if growth_stable_since
                    else 0
                )

                if stable_duration >= self.growth_timeout:
                    if has_grown and current_size >= self.min_size_bytes:
                        logging.debug(
                            f"File {tracked_file.file_path} finished growing, ready for growing copy "
                            f"(size: {current_size / 1024 / 1024:.1f}MB)"
                        )
                        return FileStatus.READY_TO_START_GROWING, updated_file
                    else:
                        # File is stable - either never grew OR is a small file
                        # Use READY for normal copy workflow
                        logging.debug(
                            f"File {tracked_file.file_path} is stable, ready for normal copy "
                            f"(size: {current_size / 1024 / 1024:.1f}MB, has_grown: {has_grown})"
                        )
                        return FileStatus.READY, updated_file
                else:
                    if has_grown:
                        logging.debug(
                            f"File {tracked_file.file_path} previously grew, checking post-growth stability "
                            f"({stable_duration:.1f}s/{self.growth_timeout}s)"
                        )
                        return FileStatus.GROWING, updated_file
                    else:
                        logging.debug(
                            f"File {tracked_file.file_path} checking initial stability "
                            f"({stable_duration:.1f}s/{self.growth_timeout}s)"
                        )
                        return FileStatus.DISCOVERED, updated_file

        except Exception as e:
            logging.error(
                f"Error checking growth status for {tracked_file.file_path}: {e}"
            )
            return FileStatus.FAILED, None

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

    async def _monitor_growing_files_loop(self):
        logging.info("Starting growing file monitoring loop")

        while self._monitoring_active:
            try:
                # Get all files that need growth monitoring via CQRS
                query = GetFilesNeedingGrowthMonitoringQuery()
                growing_files = await self._query_bus.execute(query)

                for tracked_file in growing_files:
                    if not self._monitoring_active:
                        break

                    try:
                        (
                            recommended_status,
                            updated_file,
                        ) = await self.check_file_growth_status(tracked_file)

                        if recommended_status != tracked_file.status:
                            # Update file status via CQRS based on growth decision
                            if recommended_status == FileStatus.GROWING:
                                command = MarkFileGrowingCommand(
                                    file_id=tracked_file.id,
                                    file_path=tracked_file.file_path
                                )
                                await self._command_bus.execute(command)
                            elif recommended_status == FileStatus.READY_TO_START_GROWING:
                                command = MarkFileReadyToStartGrowingCommand(
                                    file_id=tracked_file.id,
                                    file_path=tracked_file.file_path
                                )
                                await self._command_bus.execute(command)
                            # For other statuses, we could add more commands as needed
                            
                            logging.debug(
                                f"GROWING UPDATE: {tracked_file.file_path} -> {recommended_status} [UUID: {tracked_file.id[:8]}...]"
                            )

                    except Exception as e:
                        logging.error(
                            f"Error monitoring growth for {tracked_file.id}: {e}"
                        )

                await asyncio.sleep(self.poll_interval)

            except Exception as e:
                logging.error(f"Error in growing file monitoring loop: {e}")
                await asyncio.sleep(self.poll_interval)

        logging.info("Growing file monitoring loop stopped")
