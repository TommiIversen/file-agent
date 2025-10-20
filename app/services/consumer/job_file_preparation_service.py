"""
Job File Preparation Service for File Transfer Agent.

Responsible solely for preparing files for copy operations.
Extracted from JobProcessor to follow Single Responsibility Principle and eliminate local import violations.

This service handles:
- File validation and retrieval from state manager
- Copy strategy selection based on file characteristics
- Initial status determination for copy operations
- Destination path calculation with template engine support
- Conflict-free path generation
"""

import logging
from typing import Optional
from pathlib import Path

from app.config import Settings
from app.models import FileStatus
from app.services.state_manager import StateManager
from app.services.copy_strategies import CopyStrategyFactory
from app.utils.output_folder_template import OutputFolderTemplateEngine
from app.utils.file_operations import (
    build_destination_path_with_template,
    generate_conflict_free_path,
)
from app.services.consumer.job_models import PreparedFile, QueueJob


class JobFilePreparationService:
    """
    Responsible solely for preparing files for copy operations.

    This class adheres to SRP by handling only file preparation concerns
    including strategy selection and destination path calculation.
    """

    def __init__(
        self,
        settings: Settings,
        state_manager: StateManager,
        copy_strategy_factory: CopyStrategyFactory,
        template_engine: OutputFolderTemplateEngine,
    ):
        """
        Initialize JobFilePreparationService with required dependencies.

        Args:
            settings: Application settings for source/destination directories
            state_manager: Central state manager for file retrieval
            copy_strategy_factory: Factory for copy strategy selection
            template_engine: Template engine for destination path generation
        """
        self.settings = settings
        self.state_manager = state_manager
        self.copy_strategy_factory = copy_strategy_factory
        self.template_engine = template_engine

        logging.debug("JobFilePreparationService initialized")

    async def prepare_file_for_copy(self, job: QueueJob) -> Optional[PreparedFile]:
        """
        Prepare file information for copying with strategy selection.

        Args:
            job: QueueJob object containing file information

        Returns:
            PreparedFile with validated information, or None if file not found
        """
        # Use tracked file directly from job - no path-based lookup needed
        tracked_file = job.tracked_file
        file_path = job.file_path

        # Select appropriate copy strategy
        strategy = self.copy_strategy_factory.get_strategy(tracked_file)
        strategy_name = strategy.__class__.__name__

        # Determine initial status based on strategy
        initial_status = self._determine_initial_status(strategy_name)

        # Calculate destination path using template engine
        destination_path = self._calculate_destination_path(file_path)

        return PreparedFile(
            tracked_file=tracked_file,
            strategy_name=strategy_name,
            initial_status=initial_status,
            destination_path=destination_path,
        )

    def _determine_initial_status(self, strategy_name: str) -> FileStatus:
        """
        Determine initial file status based on copy strategy.

        Args:
            strategy_name: Name of the selected copy strategy

        Returns:
            Appropriate FileStatus for the strategy
        """
        if strategy_name == "GrowingFileCopyStrategy":
            return FileStatus.GROWING_COPY
        else:
            return FileStatus.COPYING

    def _calculate_destination_path(self, file_path: str) -> Path:
        """
        Calculate destination path using template engine if enabled.

        Args:
            file_path: Source file path

        Returns:
            Conflict-free destination path
        """
        source = Path(file_path)
        source_base = Path(self.settings.source_directory)
        dest_base = Path(self.settings.destination_directory)

        # Use template engine for path generation
        dest_path = build_destination_path_with_template(
            source, source_base, dest_base, self.template_engine
        )

        # Ensure path is conflict-free
        return generate_conflict_free_path(Path(dest_path))

    def get_preparation_info(self) -> dict:
        """
        Get information about the file preparation service configuration.

        Returns:
            Dictionary with preparation service configuration details
        """
        return {
            "template_engine_enabled": self.template_engine.is_enabled(),
            "template_rules_count": len(self.template_engine.rules)
            if self.template_engine.is_enabled()
            else 0,
            "copy_strategies_available": len(
                self.copy_strategy_factory.get_available_strategies()
            ),
            "source_directory": self.settings.source_directory,
            "destination_directory": self.settings.destination_directory,
        }
