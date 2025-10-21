"""
Job File Preparation Service - prepares files for copy operations.
"""

import logging
from pathlib import Path
from typing import Optional

from app.config import Settings
from app.models import FileStatus, TrackedFile
from app.services.consumer.job_models import PreparedFile, QueueJob
from app.services.copy_strategies import CopyStrategyFactory
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
            copy_strategy_factory: CopyStrategyFactory,
            template_engine: OutputFolderTemplateEngine,
    ):
        self.settings = settings
        self.state_manager = state_manager
        self.copy_strategy_factory = copy_strategy_factory
        self.template_engine = template_engine

    async def prepare_file_for_copy(self, job: QueueJob) -> Optional[PreparedFile]:
        """Prepare file information for copying with strategy selection."""
        tracked_file = job.tracked_file
        file_path = job.file_path

        strategy = self.copy_strategy_factory.get_strategy(tracked_file)
        strategy_name = strategy.__class__.__name__

        initial_status = self._determine_initial_status(strategy_name)
        destination_path = self._calculate_destination_path(file_path, tracked_file)

        return PreparedFile(
            tracked_file=tracked_file,
            strategy_name=strategy_name,
            initial_status=initial_status,
            destination_path=destination_path,
        )

    def _determine_initial_status(self, strategy_name: str) -> FileStatus:
        """Determine initial file status based on copy strategy."""
        if strategy_name == "GrowingFileCopyStrategy":
            return FileStatus.GROWING_COPY
        else:
            return FileStatus.COPYING

    def _calculate_destination_path(self, file_path: str, tracked_file: TrackedFile = None) -> Path:
        """Calculate destination path using template engine if enabled."""
        source = Path(file_path)
        source_base = Path(self.settings.source_directory)
        dest_base = Path(self.settings.destination_directory)

        dest_path = build_destination_path_with_template(
            source, source_base, dest_base, self.template_engine
        )

        # CRITICAL: For growing copy resume scenarios, don't resolve conflicts
        # We want to reuse the existing destination file
        if tracked_file and self._is_resume_scenario(tracked_file):
            logging.debug(
                f"RESUME DETECTED: Skipping conflict resolution for {source.name} "
                f"(bytes_copied: {tracked_file.bytes_copied:,})"
            )
            return Path(dest_path)
        
        return generate_conflict_free_path(Path(dest_path))
    
    def _is_resume_scenario(self, tracked_file: TrackedFile) -> bool:
        """Check if this is a resume scenario where we should reuse existing destination."""
        return (
            tracked_file.bytes_copied > 0 and 
            tracked_file.status == FileStatus.GROWING_COPY and
            tracked_file.is_growing_file
        )

    def get_preparation_info(self) -> dict:
        """Get file preparation service configuration details."""
        return {
            "template_engine_enabled": self.template_engine.is_enabled(),
            "template_rules_count": len(self.template_engine.rules) if self.template_engine.is_enabled() else 0,
            "copy_strategies_available": len(self.copy_strategy_factory.get_available_strategies()),
            "source_directory": self.settings.source_directory,
            "destination_directory": self.settings.destination_directory,
        }
