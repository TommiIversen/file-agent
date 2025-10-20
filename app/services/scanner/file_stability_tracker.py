# This class is responsible solely for tracking file stability, adhering to SRP.
import logging
from datetime import datetime, timedelta
from typing import Dict
from .domain_objects import FileMetadata, ScanConfiguration


class FileStabilityTracker:
    """
    Focused service responsible only for tracking file stability and growth.

    Single Responsibility: File stability determination and tracking
    """

    def __init__(self, config: ScanConfiguration):
        self.config = config
        # Internal tracking for file stability
        self._file_last_seen: Dict[str, datetime] = {}
        self._file_last_write_times: Dict[str, datetime] = {}

    def initialize_file_tracking(
        self, file_path: str, last_write_time: datetime
    ) -> None:
        """Initialize tracking for a new file."""
        self._file_last_seen[file_path] = datetime.now()
        self._file_last_write_times[file_path] = last_write_time

    def remove_file_tracking(self, file_path: str) -> None:
        """Remove tracking data for a file."""
        self._file_last_seen.pop(file_path, None)
        self._file_last_write_times.pop(file_path, None)

    def cleanup_tracking_for_missing_files(self, existing_files: set[str]) -> None:
        """Remove tracking data for files that no longer exist."""
        paths_to_remove = set(self._file_last_seen.keys()) - existing_files
        for path in paths_to_remove:
            self.remove_file_tracking(path)

    async def check_file_stability(self, metadata: FileMetadata) -> bool:
        """
        Check if a file is stable using traditional stability logic.

        Returns:
            True if file is stable and ready for processing
        """
        file_path = metadata.path.path

        # Check if write time has changed
        previous_write_time = self._file_last_write_times.get(file_path)
        if previous_write_time != metadata.last_write_time:
            # File is still being written to - update tracking
            self._update_file_tracking(file_path, metadata.last_write_time)
            return False

        # Check if file has been stable long enough using domain object
        last_seen = self._file_last_seen.get(file_path, datetime.now())
        stable_duration = timedelta(seconds=self.config.file_stable_time_seconds)

        is_stable = metadata.is_stable(stable_duration, last_seen)

        if is_stable:
            logging.info(f"File is stable and ready: {metadata.path.name}")

        return is_stable

    def _update_file_tracking(self, file_path: str, last_write_time: datetime) -> None:
        """Update internal tracking when file changes - encapsulated logic."""
        self._file_last_write_times[file_path] = last_write_time
        self._file_last_seen[file_path] = datetime.now()

    async def update_file_growth_tracking(
        self, file_path: str, current_metadata: FileMetadata, previous_size: int
    ) -> bool:
        """
        Update tracking for a growing file.

        Returns:
            True if file size changed
        """
        if current_metadata.size != previous_size:
            logging.info(
                f"File size changed: {current_metadata.path.name} "
                f"{previous_size / (1024 * 1024):.2f}MB → {current_metadata.size_mb():.2f}MB"
            )
            return True
        return False
