"""
Job Finalization Service - handles completion of copy jobs.
"""

import logging
from datetime import datetime, timezone

from app.config import Settings
from app.core.events.event_bus import DomainEventBus
from app.core.file_state_machine import FileStateMachine
from app.core.exceptions import InvalidTransitionError
from app.models import FileStatus
from app.domains.file_processing.consumer.job_models import QueueJob
from app.core.file_repository import FileRepository
from app.core.events.file_events import FileCopyCompletedEvent, FileCopyFailedEvent


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
        tracked_file = await self.file_repository.get_by_id(job.file_id)
        if not tracked_file:
            raise ValueError(f"TrackedFile not found for job {job.file_path} in finalize_success")

        # Copy strategy may have already transitioned to COMPLETED with correct bytes.
        # Re-publishing here with stale job.file_size would overwrite the UI.
        if tracked_file.status in (FileStatus.COMPLETED, FileStatus.COMPLETED_DELETE_FAILED):
            logging.debug(
                f"Skipping finalization for {job.file_path} as it is already {tracked_file.status.value}"
            )
            return

        try:
            await self.state_machine.transition(
                file_id=tracked_file.id,
                new_status=FileStatus.COMPLETED,
                copy_progress=100.0,
                bytes_copied=file_size,
                file_size=file_size,
            )
        except (InvalidTransitionError, ValueError) as e:
            logging.warning(f"Could not finalize success for {tracked_file.id}: {e}")
            return

        await self.event_bus.publish(FileCopyCompletedEvent(
            file_id=tracked_file.id,
            file_path=tracked_file.file_path,
            destination_path=getattr(tracked_file, "destination_path", None) or "",
            bytes_copied=file_size,
            source_size=file_size,
            dest_size=file_size,
        ))
        logging.info(f"Job completed successfully: {job.file_path}")

    async def finalize_failure(self, job: QueueJob, error: Exception) -> None:
        """Finalize failed job with error handling."""
        tracked_file = await self.file_repository.get_by_id(job.file_id)
        if not tracked_file:
            raise ValueError(f"TrackedFile not found for job {job.file_path} in finalize_failure")

        error_message = str(error)

        try:
            await self.state_machine.transition(
                file_id=tracked_file.id,
                new_status=FileStatus.FAILED,
                error_message=error_message,
                failed_at=datetime.now(timezone.utc),
            )
        except (InvalidTransitionError, ValueError) as e:
            logging.warning(f"Could not finalize failure for {tracked_file.id}: {e}")
            return

        await self.event_bus.publish(FileCopyFailedEvent(
            file_id=tracked_file.id,
            file_path=tracked_file.file_path,
            error_message=error_message,
        ))

    async def finalize_max_retries(self, job: QueueJob) -> None:
        """Finalize job that failed after maximum retry attempts."""
        error = RuntimeError(
            f"Failed after {self.settings.max_retry_attempts} retry attempts"
        )
        await self.finalize_failure(job, error)
        logging.error(f"Job failed after max retries: {job.file_path}")

    def get_finalization_info(self) -> dict:
        """Get finalization service configuration details."""
        return {
            "max_retry_attempts": self.settings.max_retry_attempts,
            "file_repository_available": self.file_repository is not None,
            "state_machine_available": self.state_machine is not None,
        }
