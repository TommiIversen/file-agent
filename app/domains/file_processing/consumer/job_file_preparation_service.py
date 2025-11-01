"""
Job File Preparation Service - prepares files for copy operations.
"""

import logging
from pathlib import Path
from typing import Optional

from app.config import Settings
from app.models import FileStatus
from app.domains.file_processing.consumer.job_models import PreparedFile, QueueJob
from app.domains.file_processing.copy.growing_copy import GrowingFileCopyStrategy
from app.core.file_repository import FileRepository
from app.core.events.event_bus import DomainEventBus
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
        file_repository: FileRepository,
        event_bus: DomainEventBus,
        copy_strategy: GrowingFileCopyStrategy,
        template_engine: OutputFolderTemplateEngine,
    ):
        self.settings = settings
        self.file_repository = file_repository
        self.event_bus = event_bus
        self.copy_strategy = copy_strategy
        self.template_engine = template_engine

    async def prepare_file_for_copy(self, job: QueueJob) -> Optional[PreparedFile]:
        """Prepare file information for copying with strategy selection."""
        file_path = job.file_path

        strategy_name = self.copy_strategy.__class__.__name__

        initial_status = await self._determine_file_status(job)
        destination_path = await self._calculate_destination_path(file_path)

        # Eksempel på Update & Announce hvis destination_path skal gemmes
        # old_status = tracked_file.status
        # tracked_file.destination_path = str(destination_path)
        # await self.file_repository.update(tracked_file)
        # Hvis status ændres, publicer event:
        # if tracked_file.status != old_status:
        #     await self.event_bus.publish(FileStatusChangedEvent(
        #         file_id=tracked_file.id,
        #         file_path=tracked_file.file_path,
        #         old_status=old_status,
        #         new_status=tracked_file.status,
        #         timestamp=datetime.now()
        #     ))

        return PreparedFile(
            job=job,
            strategy_name=strategy_name,
            initial_status=initial_status,
            destination_path=destination_path,
        )

    async def _determine_file_status(self, job: QueueJob) -> FileStatus:
        """Determine initial file status based on whether file is static or growing."""
        tracked_file = await self.file_repository.get_by_id(job.file_id)
        if not tracked_file:
            logging.warning(f"Tracked file not found for job ID: {job.file_id} in _determine_file_status.")
            # Default to static copy if tracked file is not found, copy will likely fail later.
            return FileStatus.COPYING

        # If file is already in copy processing (COPYING or GROWING_COPY), keep current status
        # This prevents infinite loops where we re-evaluate files already being processed
        if tracked_file.status in [FileStatus.COPYING, FileStatus.GROWING_COPY]:
            logging.debug(f"🔄 File already in copy processing with status {tracked_file.status}: {job.file_path}")
            return tracked_file.status

        if job.is_growing_at_queue_time:
            logging.info(f"🌱 File marked for GROWING_COPY (from queue snapshot): {job.file_path}")
            return FileStatus.GROWING_COPY
        else:
            logging.info(f"⚡ File marked for STATIC COPY (from queue snapshot): {job.file_path}")
            return FileStatus.COPYING  # Static files go straight to copying

    async def _calculate_destination_path(self, file_path: str) -> Path:
        """Calculate destination path using template engine if enabled."""
        source = Path(file_path)
        source_base = Path(self.settings.source_directory)
        dest_base = Path(self.settings.destination_directory)

        dest_path = build_destination_path_with_template(
            source, source_base, dest_base, self.template_engine
        )

        return await generate_conflict_free_path(Path(dest_path))

    def get_preparation_info(self) -> dict:
        """Get file preparation service configuration details."""
        return {
            "template_engine_enabled": self.template_engine.is_enabled(),
            "template_rules_count": len(self.template_engine.rules)
            if self.template_engine.is_enabled()
            else 0,
            "copy_strategy": self.copy_strategy.__class__.__name__,
            "source_directory": self.settings.source_directory,
            "destination_directory": self.settings.destination_directory,
        }
