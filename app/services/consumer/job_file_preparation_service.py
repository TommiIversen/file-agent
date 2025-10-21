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

        # CRITICAL: Re-evaluate growing status real-time for strategy selection
        # This ensures files that went WAITING_FOR_NETWORK -> READY get correct strategy
        updated_tracked_file = await self._refresh_growing_status(tracked_file)
        
        strategy = self.copy_strategy_factory.get_strategy(updated_tracked_file)
        strategy_name = strategy.__class__.__name__

        initial_status = self._determine_initial_status(strategy_name)
        destination_path = self._calculate_destination_path(file_path, updated_tracked_file)

        return PreparedFile(
            tracked_file=updated_tracked_file,
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

        # NOTE: Resume scenario detection removed in fail-and-rediscover strategy
        # All files now get conflict-free paths with _1 naming for recovery
        
        if tracked_file:
            logging.debug(
                f"⚠️ NOT RESUME: Applying conflict resolution for {source.name} "
                f"(bytes_copied: {tracked_file.bytes_copied:,}, status: {tracked_file.status}, "
                f"is_growing: {tracked_file.is_growing_file})"
            )
        
        return generate_conflict_free_path(Path(dest_path))
    
    # NOTE: _is_resume_scenario removed in fail-and-rediscover strategy
    # Files now get fresh destinations with _1 naming for recovery

    def get_preparation_info(self) -> dict:
        """Get file preparation service configuration details."""
        return {
            "template_engine_enabled": self.template_engine.is_enabled(),
            "template_rules_count": len(self.template_engine.rules) if self.template_engine.is_enabled() else 0,
            "copy_strategies_available": len(self.copy_strategy_factory.get_available_strategies()),
            "source_directory": self.settings.source_directory,
            "destination_directory": self.settings.destination_directory,
        }

    async def _refresh_growing_status(self, tracked_file: TrackedFile) -> TrackedFile:
        """
        Re-evaluate if a file is currently growing for accurate strategy selection.
        This is critical for files that went WAITING_FOR_NETWORK -> READY.
        """
        import os
        from datetime import datetime
        
        # Handle None tracked_file gracefully
        if not tracked_file:
            return tracked_file
        
        try:
            if not os.path.exists(tracked_file.file_path):
                return tracked_file
                
            current_size = os.path.getsize(tracked_file.file_path)
            current_time = datetime.now()
            
            # If file size has changed from last known size, it's growing
            if tracked_file.file_size and current_size > tracked_file.file_size:
                logging.info(
                    f"🌱 REAL-TIME GROWTH DETECTED: {os.path.basename(tracked_file.file_path)} "
                    f"grew from {tracked_file.file_size:,} to {current_size:,} bytes - selecting growing strategy"
                )
                
                # Update the tracked file to reflect growing status
                await self.state_manager.update_file_status_by_id(
                    tracked_file.id,
                    tracked_file.status,  # Keep current status
                    file_size=current_size,
                    is_growing_file=True,
                    last_growth_check=current_time,
                )
                
                # Get fresh copy from state manager
                fresh_file = await self.state_manager.get_file_by_id(tracked_file.id)
                return fresh_file or tracked_file
            else:
                # File hasn't grown - but check if it was marked as growing before
                if tracked_file.is_growing_file:
                    logging.debug(
                        f"📊 GROWTH STATUS PRESERVED: {os.path.basename(tracked_file.file_path)} "
                        f"still marked as growing (size: {current_size:,})"
                    )
                    
                return tracked_file
                
        except Exception as e:
            file_path = tracked_file.file_path if tracked_file else "unknown"
            logging.warning(f"Failed to refresh growing status for {file_path}: {e}")
            return tracked_file
