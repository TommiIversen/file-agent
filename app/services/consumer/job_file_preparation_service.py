"""
Job File Preparation Service - prepares files for copy operations.
"""

import logging
from pathlib import Path
from typing import Optional

from app.config import Settings
from app.models import FileStatus, TrackedFile
from app.services.consumer.job_models import PreparedFile, QueueJob
from app.services.copy_strategies import GrowingFileCopyStrategy
from app.services.state_manager import StateManager
from app.utils.file_operations import (
    build_destination_path_with_template,
    generate_conflict_free_path,
)
from app.utils.output_folder_template import OutputFolderTemplateEngine


class JobFilePreparationService:
    """Prepares files for copy operations with strategy selection and path calculation."""

    def __init__(
            self,
            settings: Settings,
            state_manager: StateManager,
            copy_strategy: GrowingFileCopyStrategy,
            template_engine: OutputFolderTemplateEngine,
    ):
        self.settings = settings
        self.state_manager = state_manager
        self.copy_strategy = copy_strategy
        self.template_engine = template_engine

    async def prepare_file_for_copy(self, job: QueueJob) -> Optional[PreparedFile]:
        """Prepare file information for copying with strategy selection."""
        tracked_file = job.tracked_file
        file_path = job.file_path

        strategy_name = self.copy_strategy.__class__.__name__

        initial_status = self._determine_initial_status(tracked_file)
        destination_path = self._calculate_destination_path(file_path)

        return PreparedFile(
            tracked_file=tracked_file,
            strategy_name=strategy_name,
            initial_status=initial_status,
            destination_path=destination_path,
        )

    def _determine_initial_status(self, tracked_file: Optional[TrackedFile]) -> FileStatus:
        """Determine initial file status based on whether file is static or growing."""
        if not tracked_file:
            # If there's no tracked file, it cannot be growing. Default to static copy.
            # The copy operation will likely fail later, but this method shouldn't crash.
            return FileStatus.COPYING

        # Use the copy strategy's logic to determine if this is a growing file
        is_growing_file = self.copy_strategy._is_file_currently_growing(tracked_file)

        if is_growing_file:
            logging.info(f"🌱 File marked for GROWING_COPY: {tracked_file.file_path}")
            return FileStatus.GROWING_COPY
        else:
            logging.info(f"⚡ File marked for STATIC COPY: {tracked_file.file_path}")
            return FileStatus.COPYING  # Static files go straight to copying

    def _calculate_destination_path(self, file_path: str) -> Path:
        """Calculate destination path using template engine if enabled."""
        source = Path(file_path)
        source_base = Path(self.settings.source_directory)
        dest_base = Path(self.settings.destination_directory)

        dest_path = build_destination_path_with_template(
            source, source_base, dest_base, self.template_engine
        )

        return generate_conflict_free_path(Path(dest_path))

    def get_preparation_info(self) -> dict:
        """Get file preparation service configuration details."""
        return {
            "template_engine_enabled": self.template_engine.is_enabled(),
            "template_rules_count": len(self.template_engine.rules) if self.template_engine.is_enabled() else 0,
            "copy_strategy": self.copy_strategy.__class__.__name__,
            "source_directory": self.settings.source_directory,
            "destination_directory": self.settings.destination_directory,
        }
