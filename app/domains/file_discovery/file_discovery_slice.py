"""
File Discovery Domain Slice
Implements the vertical slice for file discovery operations using CQRS pattern.
Matches the original StateManager logic for file discovery and status management.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, List

from app.core.events.event_bus import DomainEventBus
from app.core.events.file_events import FileDiscoveredEvent, FileReadyEvent
from app.core.file_repository import FileRepository
from app.models import TrackedFile, FileStatus


class FileDiscoverySlice:
    """
    Vertical slice containing all file discovery related business logic.
    Responsible for: file discovery, stability tracking, cooldown logic, path prioritization.
    """

    def __init__(
        self, 
        file_repository: FileRepository, 
        event_bus: Optional[DomainEventBus] = None,
        cooldown_minutes: int = 60
    ):
        self._file_repository = file_repository
        self._event_bus = event_bus
        self._cooldown_minutes = cooldown_minutes
        logging.info("FileDiscoverySlice initialized")

    async def get_active_file_by_path(self, file_path: str) -> Optional[TrackedFile]:
        """
        Get the currently active file for a given path.
        Matches original StateManager._get_active_file_for_path_internal logic exactly.
        """
        active_statuses = {
            FileStatus.DISCOVERED,
            FileStatus.READY,
            FileStatus.GROWING,
            FileStatus.READY_TO_START_GROWING,
            FileStatus.IN_QUEUE,
            FileStatus.COPYING,
            FileStatus.GROWING_COPY,
            FileStatus.WAITING_FOR_SPACE,
            FileStatus.SPACE_ERROR,
            FileStatus.WAITING_FOR_NETWORK,
        }
        
        all_files = await self._file_repository.get_all()
        candidates = [
            f for f in all_files 
            if f.file_path == file_path and f.status in active_statuses
        ]
        
        if not candidates:
            return None

        # Sort by priority: active operations first, then by discovery time
        # Matches original StateManager sort_key logic exactly
        def sort_key(f: TrackedFile):
            active_priority = {
                FileStatus.COPYING: 1,
                FileStatus.IN_QUEUE: 2,
                FileStatus.GROWING_COPY: 3,
                FileStatus.READY_TO_START_GROWING: 4,
                FileStatus.READY: 5,
                FileStatus.GROWING: 6,
                FileStatus.DISCOVERED: 7,
                FileStatus.WAITING_FOR_SPACE: 8,
                FileStatus.WAITING_FOR_NETWORK: 8,
                FileStatus.SPACE_ERROR: 9,
            }
            priority = active_priority.get(f.status, 99)
            time_priority = -(f.discovered_at.timestamp() if f.discovered_at else 0)
            return (priority, time_priority)

        return min(candidates, key=sort_key)

    async def get_current_file_for_path(self, file_path: str) -> Optional[TrackedFile]:
        """
        Get the current file for a path, including inactive files.
        Matches original StateManager._get_current_file_for_path logic exactly.
        """
        all_files = await self._file_repository.get_all()
        candidates = [f for f in all_files if f.file_path == file_path]
        if not candidates:
            return None

        # Matches original StateManager sort_key logic exactly
        def sort_key(f: TrackedFile):
            status_priority = {
                FileStatus.COPYING: 1,
                FileStatus.IN_QUEUE: 2,
                FileStatus.GROWING_COPY: 3,
                FileStatus.READY_TO_START_GROWING: 4,
                FileStatus.READY: 5,
                FileStatus.GROWING: 6,
                FileStatus.DISCOVERED: 7,
                FileStatus.WAITING_FOR_SPACE: 8,
                FileStatus.WAITING_FOR_NETWORK: 9,
                FileStatus.COMPLETED: 10,
                FileStatus.FAILED: 11,
                FileStatus.REMOVED: 12,
                FileStatus.SPACE_ERROR: 13,
            }
            priority = status_priority.get(f.status, 99)
            time_priority = -(f.discovered_at.timestamp() if f.discovered_at else 0)
            return (priority, time_priority)

        return min(candidates, key=sort_key)

    def _is_space_error_in_cooldown(self, tracked_file: TrackedFile) -> bool:
        """
        Check if a file with space error is still in cooldown period.
        Matches original StateManager._is_space_error_in_cooldown logic exactly.
        """
        if tracked_file.status != FileStatus.SPACE_ERROR:
            return False
        
        if not tracked_file.space_error_at:
            return False
        
        cooldown_duration = timedelta(minutes=self._cooldown_minutes)
        time_since_error = datetime.now() - tracked_file.space_error_at
        is_in_cooldown = time_since_error < cooldown_duration
        
        if is_in_cooldown:
            remaining_minutes = (cooldown_duration - time_since_error).total_seconds() / 60
            logging.debug(
                f"File {tracked_file.file_path} in SPACE_ERROR cooldown - "
                f"{remaining_minutes:.1f} minutes remaining"
            )
        
        return is_in_cooldown

    async def should_skip_file_processing(self, file_path: str) -> bool:
        """
        Determine if file processing should be skipped due to cooldown or other rules.
        Matches original StateManager.should_skip_file_processing logic exactly.
        """
        existing_file = await self.get_current_file_for_path(file_path)
        if not existing_file:
            return False
        
        if existing_file.status == FileStatus.SPACE_ERROR:
            return self._is_space_error_in_cooldown(existing_file)
        
        return False

    async def add_discovered_file(
        self, 
        file_path: str, 
        file_size: int, 
        last_write_time: Optional[datetime] = None
    ) -> TrackedFile:
        """
        Add a newly discovered file to the system.
        Matches original StateManager.add_file logic exactly.
        """
        # Check if there's already an active file for this path
        existing_active = await self.get_active_file_by_path(file_path)
        if existing_active:
            logging.debug(f"Fil allerede tracked som aktiv: {file_path}")
            return existing_active
        
        # Check for any existing file (including inactive)
        any_existing = await self.get_current_file_for_path(file_path)
        
        # Create new tracked file
        tracked_file = TrackedFile(
            file_path=file_path,
            file_size=file_size,
            last_write_time=last_write_time,
            status=FileStatus.DISCOVERED,
        )
        
        await self._file_repository.add(tracked_file)
        
        # Log appropriate message based on existing file status
        if any_existing and any_existing.status == FileStatus.REMOVED:
            logging.info(
                f"File returned after REMOVED - creating new entry: {file_path}"
            )
            logging.info(
                f"Previous REMOVED entry preserved as history: {any_existing.id}"
            )
        elif any_existing and any_existing.status in [
            FileStatus.COMPLETED,
            FileStatus.FAILED,
        ]:
            logging.info(
                f"Ny fil med samme navn som completed/failed fil: {file_path} "
                f"(Previous: {any_existing.id[:8]}..., New: {tracked_file.id[:8]}...)"
            )
        else:
            logging.info(f"Ny fil tilføjet: {file_path} ({file_size} bytes)")

        # Publish events
        if self._event_bus:
            # Publish discovery event
            discovery_event = FileDiscoveredEvent(
                file_path=file_path,
                file_size=file_size,
                last_write_time=last_write_time.timestamp() if last_write_time else datetime.now().timestamp()
            )
            await self._event_bus.publish(discovery_event)

        return tracked_file

    async def mark_file_ready(self, file_id: str) -> bool:
        """
        Mark a file as ready for processing.
        Returns True if successful, False if file not found.
        """
        file = await self._file_repository.get_by_id(file_id)
        if not file:
            return False

        # Update file status
        file.status = FileStatus.READY
        
        await self._file_repository.update(file)  # Use update for existing files
        
        # Publish ready event
        if self._event_bus:
            event = FileReadyEvent(file_id=file_id, file_path=file.file_path)
            await self._event_bus.publish(event)

        logging.info(f"File marked as ready: {file.file_path}")
        return True

    async def get_files_by_status(self, status: FileStatus) -> List[TrackedFile]:
        """
        Get all files with a specific status.
        Matches original StateManager.get_files_by_status logic exactly.
        Returns only the most current file for each path.
        """
        current_files = {}
        all_files = await self._file_repository.get_all()
        
        for tracked_file in all_files:
            if tracked_file.status == status:
                current = current_files.get(tracked_file.file_path)
                if not current or self._is_more_current(tracked_file, current):
                    current_files[tracked_file.file_path] = tracked_file
        
        return list(current_files.values())

    def _is_more_current(self, file1: TrackedFile, file2: TrackedFile) -> bool:
        """
        Determine if file1 is more current than file2.
        Matches original StateManager._is_more_current logic exactly.
        """
        active_statuses = {
            FileStatus.COPYING: 1,
            FileStatus.IN_QUEUE: 2,
            FileStatus.GROWING_COPY: 3,
            FileStatus.READY_TO_START_GROWING: 4,
            FileStatus.READY: 5,
            FileStatus.GROWING: 6,
            FileStatus.DISCOVERED: 7,
            FileStatus.WAITING_FOR_SPACE: 8,
            FileStatus.WAITING_FOR_NETWORK: 8,
            FileStatus.COMPLETED: 9,
            FileStatus.FAILED: 10,
            FileStatus.REMOVED: 11,
            FileStatus.SPACE_ERROR: 12,
        }
        
        priority1 = active_statuses.get(file1.status, 99)
        priority2 = active_statuses.get(file2.status, 99)
        
        if priority1 != priority2:
            return priority1 < priority2
        
        time1 = file1.discovered_at.timestamp() if file1.discovered_at else 0
        time2 = file2.discovered_at.timestamp() if file2.discovered_at else 0
        return time1 > time2

    async def get_files_needing_growth_monitoring(self) -> List[TrackedFile]:
        """
        Get all files that need growth monitoring.
        Returns files that have last_growth_check set and are in growth-related states.
        """
        all_files = await self._file_repository.get_all()
        growth_statuses = {
            FileStatus.DISCOVERED,
            FileStatus.GROWING,
            FileStatus.READY_TO_START_GROWING,
        }
        
        return [
            f for f in all_files
            if f.last_growth_check is not None and f.status in growth_statuses
            and f.status not in {
                FileStatus.IN_QUEUE,
                FileStatus.COPYING,
                FileStatus.GROWING_COPY,
                FileStatus.COMPLETED,
                FileStatus.FAILED,
                FileStatus.REMOVED,
                FileStatus.SPACE_ERROR,
                FileStatus.WAITING_FOR_NETWORK,
            }
        ]

    async def update_file_growth_info(
        self,
        file_id: str,
        file_size: int,
        previous_file_size: Optional[int] = None,
        growth_rate_mbps: Optional[float] = None,
        growth_stable_since: Optional[datetime] = None,
        last_growth_check: Optional[datetime] = None
    ) -> bool:
        """
        Update file growth information.
        Returns True if successful, False if file not found.
        """
        file = await self._file_repository.get_by_id(file_id)
        if not file:
            return False

        # Update growth information
        file.file_size = file_size
        if previous_file_size is not None:
            file.previous_file_size = previous_file_size
        if growth_rate_mbps is not None:
            file.growth_rate_mbps = growth_rate_mbps
        if growth_stable_since is not None:
            file.growth_stable_since = growth_stable_since
        if last_growth_check is not None:
            file.last_growth_check = last_growth_check

        await self._file_repository.update(file)
        return True

    async def mark_file_growing(self, file_id: str) -> bool:
        """
        Mark a file as growing.
        Returns True if successful, False if file not found.
        """
        file = await self._file_repository.get_by_id(file_id)
        if not file:
            return False

        file.status = FileStatus.GROWING
        await self._file_repository.update(file)
        
        logging.info(f"File marked as growing: {file.file_path}")
        return True

    async def mark_file_ready_to_start_growing(self, file_id: str) -> bool:
        """
        Mark a file as ready to start growing copy.
        Returns True if successful, False if file not found.
        """
        file = await self._file_repository.get_by_id(file_id)
        if not file:
            return False

        file.status = FileStatus.READY_TO_START_GROWING
        await self._file_repository.update(file)
        
        # Publish ready event
        if self._event_bus:
            event = FileReadyEvent(file_id=file_id, file_path=file.file_path)
            await self._event_bus.publish(event)

        logging.info(f"File marked as ready to start growing: {file.file_path}")
        return True