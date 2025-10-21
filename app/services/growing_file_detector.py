import asyncio
import logging
import os
from datetime import datetime
from typing import Optional, Tuple

from app.config import Settings
from app.models import FileStatus, TrackedFile
from app.services.state_manager import StateManager


class GrowingFileDetector:
    def __init__(self, settings: Settings, state_manager: StateManager):
        self.settings = settings
        self.state_manager = state_manager

        # Removed _growth_tracking - using StateManager as single source of truth
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
    ) -> Tuple[FileStatus, Optional[TrackedFile]]:
        """
        Check file growth status using TrackedFile state instead of separate tracking.
        Returns updated TrackedFile with growth information.
        """
        # CRITICAL: Don't modify files that are waiting for network
        # This prevents the bounce loop between READY and WAITING_FOR_NETWORK
        if tracked_file.status == FileStatus.WAITING_FOR_NETWORK:
            logging.debug(f"Skipping growth check for {tracked_file.file_path} - waiting for network")
            return tracked_file.status, tracked_file
            
        try:
            # Get current file info
            if not os.path.exists(tracked_file.file_path):
                logging.info(f"File no longer exists during growth check: {tracked_file.file_path}")
                return FileStatus.REMOVED, None

            current_size = os.path.getsize(tracked_file.file_path)
            current_time = datetime.now()

            # Initialize growth tracking fields if this is first check
            if tracked_file.last_growth_check is None:
                # First time seeing this file - initialize growth tracking
                await self.state_manager.update_file_status_by_id(
                    tracked_file.id,
                    tracked_file.status,  # Keep current status
                    file_size=current_size,
                    previous_file_size=current_size,
                    first_seen_size=current_size,
                    last_growth_check=current_time,
                    growth_stable_since=current_time,
                )
                
                # Get updated file
                updated_file = await self.state_manager.get_file_by_id(tracked_file.id)
                
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
                growth_rate = (size_diff / (1024 * 1024)) / time_diff if time_diff > 0 else 0.0
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

            # CRITICAL: Don't update paused files - they wait for network recovery
            current_file = await self.state_manager.get_file_by_id(tracked_file.id)
            if current_file and current_file.status in [
                FileStatus.PAUSED_IN_QUEUE,
                FileStatus.PAUSED_COPYING,
                FileStatus.PAUSED_GROWING_COPY,
            ]:
                logging.debug(
                    f"GROWING CHECK SKIPPED: {tracked_file.file_path} is paused "
                    f"({current_file.status.value}) - not updating growth data [UUID: {tracked_file.id[:8]}...]"
                )
                # Return current status without updating anything
                return tracked_file.status, current_file

            # Update TrackedFile with new information
            await self.state_manager.update_file_status_by_id(
                tracked_file.id,
                tracked_file.status,  # Keep current status for now
                file_size=current_size,
                previous_file_size=previous_size,
                last_growth_check=current_time,
                growth_rate_mbps=growth_rate,
                growth_stable_since=growth_stable_since,
            )

            # Get updated file for decision logic
            updated_file = await self.state_manager.get_file_by_id(tracked_file.id)

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
                            current_time - growth_stable_since
                    ).total_seconds() if growth_stable_since else 0
                    
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
                        current_time - growth_stable_since
                ).total_seconds() if growth_stable_since else 0

                if stable_duration >= self.growth_timeout:
                    if has_grown and current_size >= self.min_size_bytes:
                        logging.debug(
                            f"File {tracked_file.file_path} finished growing, ready for growing copy "
                            f"(size: {current_size / 1024 / 1024:.1f}MB)"
                        )
                        return FileStatus.READY_TO_START_GROWING, updated_file
                    else:
                        logging.debug(
                            f"File {tracked_file.file_path} is stable, ready for normal copy "
                            f"(size: {current_size / 1024 / 1024:.1f}MB)"
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
        """Update file growth information using StateManager instead of separate tracking."""
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

        # CRITICAL: Don't update paused files - they wait for network recovery
        current_file = await self.state_manager.get_file_by_id(tracked_file.id)
        if current_file and current_file.status in [
            FileStatus.PAUSED_IN_QUEUE,
            FileStatus.PAUSED_COPYING,
            FileStatus.PAUSED_GROWING_COPY,
        ]:
            logging.debug(
                f"GROWING INFO UPDATE SKIPPED: {tracked_file.file_path} is paused "
                f"({current_file.status.value}) - not updating growth info [UUID: {tracked_file.id[:8]}...]"
            )
            return  # Don't update paused files

        # Update TrackedFile with new growth information
        await self.state_manager.update_file_status_by_id(
            tracked_file.id,
            tracked_file.status,  # Keep current status
            file_size=new_size,
            previous_file_size=tracked_file.file_size,
            last_growth_check=current_time,
            growth_rate_mbps=growth_rate,
            growth_stable_since=growth_stable_since,
            first_seen_size=tracked_file.first_seen_size or new_size,  # Initialize if not set
        )

    async def _monitor_growing_files_loop(self):
        logging.info("Starting growing file monitoring loop")

        while self._monitoring_active:
            try:
                # Get all files that are being tracked for growth (have last_growth_check set)
                all_files = await self.state_manager.get_all_files()
                growing_files = [
                    f for f in all_files 
                    if f.last_growth_check is not None 
                    and f.status not in [
                        FileStatus.IN_QUEUE,
                        FileStatus.COPYING,
                        FileStatus.GROWING_COPY,
                        FileStatus.COMPLETED,
                        FileStatus.FAILED,
                        FileStatus.REMOVED,
                        FileStatus.SPACE_ERROR,  # Don't process files with permanent space errors
                        # CRITICAL: Don't process paused files - they wait for network recovery
                        FileStatus.PAUSED_IN_QUEUE,
                        FileStatus.PAUSED_COPYING,
                        FileStatus.PAUSED_GROWING_COPY,
                    ]
                ]

                for tracked_file in growing_files:
                    if not self._monitoring_active:
                        break

                    try:
                        (
                            recommended_status,
                            updated_file,
                        ) = await self.check_file_growth_status(tracked_file)

                        if recommended_status != tracked_file.status:
                            # CRITICAL: Never update paused files - they wait for network recovery
                            current_file = await self.state_manager.get_file_by_id(tracked_file.id)
                            if current_file and current_file.status in [
                                FileStatus.PAUSED_IN_QUEUE,
                                FileStatus.PAUSED_COPYING,
                                FileStatus.PAUSED_GROWING_COPY,
                            ]:
                                logging.debug(
                                    f"GROWING UPDATE SKIPPED: {tracked_file.file_path} is paused "
                                    f"({current_file.status.value}) - waiting for recovery [UUID: {tracked_file.id[:8]}...]"
                                )
                                continue  # Skip updating paused files
                            
                            update_kwargs = {
                                "is_growing_file": recommended_status
                                                   in [
                                                       FileStatus.GROWING,
                                                       FileStatus.READY_TO_START_GROWING,
                                                   ],
                            }

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
                            f"Error monitoring growth for {tracked_file.id}: {e}"
                        )

                await asyncio.sleep(self.poll_interval)

            except Exception as e:
                logging.error(f"Error in growing file monitoring loop: {e}")
                await asyncio.sleep(self.poll_interval)

        logging.info("Growing file monitoring loop stopped")
