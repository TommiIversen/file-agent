"""
Job Finalization Service - handles completion of copy jobs.
"""

import logging

from app.config import Settings
from app.core.events.event_bus import DomainEventBus
from app.core.file_state_machine import FileStateMachine
from app.models import FileStatus
from app.domains.file_processing.consumer.job_models import QueueJob
from app.core.file_repository import FileRepository
from app.core.events.file_events import FileCopyCompletedEvent


class JobFinalizationService:
    """Handles job completion workflows (success, failure, max retries)."""

    def __init__(
        self,
        settings: Settings,
        file_repository: FileRepository,
        event_bus: DomainEventBus,
        state_machine: FileStateMachine,
    ):
        self.settings = settings
        self.file_repository = file_repository
        self.event_bus = event_bus
        self.state_machine = state_machine

    async def finalize_success(self, job: QueueJob, file_size: int) -> None:
        """Finalize successful job completion."""
        # Check the current status to avoid overwriting COMPLETED_DELETE_FAILED
        tracked_file = await self.file_repository.get_by_id(job.file_id)
        if not tracked_file:
            logging.warning(f"Tracked file not found for job {job.file_path} in finalize_success")
            return
        if tracked_file.status == FileStatus.COMPLETED_DELETE_FAILED:
            logging.debug(
                f"Skipping finalization for {job.file_path} as it already has delete error status"
            )
            return

        # Use state machine for atomic status transition + field updates
        # State machine handles: repository update, event publishing,
        # auto-clearing error_message, and auto-setting completed_at.
        # IMPORTANT: Set file_size and bytes_copied so the database has the
        # definitive final values.  Without this the UI shows the stale
        # intermediate size from the last progress-update until the user
        # refreshes the page.
        await self.state_machine.transition(
            file_id=tracked_file.id,
            new_status=FileStatus.COMPLETED,
            copy_progress=100.0,
            bytes_copied=file_size,
            file_size=file_size,
        )
        
        await self.event_bus.publish(FileCopyCompletedEvent(
            file_id=tracked_file.id,
            file_path=tracked_file.file_path,
            destination_path=getattr(tracked_file, "destination_path", None) or "",
            bytes_copied=file_size, # Use the actual copied bytes from parameter
            source_size=file_size,  # Use actual size (tracked_file may be stale)
            dest_size=file_size     # Destination size (should be same for normal copies)
        ))
        logging.info(f"Job completed successfully: {job.file_path}")

    async def finalize_failure(self, job: QueueJob, error: Exception) -> None:
        """Finalize failed job with error handling."""
        error_message = str(error)
        
        # Note: Job queue management should be handled by calling JobProcessor
        
        tracked_file = await self.file_repository.get_by_id(job.file_id)
        if not tracked_file:
            logging.warning(f"Tracked file not found for job {job.file_path} in finalize_failure")
            return
            
        # Use state machine for atomic transition + error message
        await self.state_machine.transition(
            file_id=tracked_file.id,
            new_status=FileStatus.FAILED,
            error_message=error_message,
        )

    async def finalize_max_retries(self, job: QueueJob) -> None:
        """Finalize job that failed after maximum retry attempts."""
        error_message = (
            f"Failed after {self.settings.max_retry_attempts} retry attempts"
        )
        
        # Note: Job queue management should be handled by calling JobProcessor

        tracked_file = await self.file_repository.get_by_id(job.file_id)
        if not tracked_file:
            logging.warning(f"Tracked file not found for job {job.file_path} in finalize_max_retries")
            return

        # Use state machine for atomic transition + error message
        await self.state_machine.transition(
            file_id=tracked_file.id,
            new_status=FileStatus.FAILED,
            error_message=error_message,
        )
        
        logging.error(f"Job failed after max retries: {job.file_path}")

    def get_finalization_info(self) -> dict:
        """Get finalization service configuration details."""
        return {
            "max_retry_attempts": self.settings.max_retry_attempts,
            "file_repository_available": self.file_repository is not None,
            "state_machine_available": self.state_machine is not None,
        }
