"""
Job Finalization Service - handles completion of copy jobs.
"""

import logging
from typing import Optional

from app.config import Settings
from app.core.events.event_bus import DomainEventBus
from app.models import FileStatus
from app.services.consumer.job_models import QueueJob
from app.services.job_queue import JobQueueService
from app.services.state_manager import StateManager


class JobFinalizationService:
    """Handles job completion workflows (success, failure, max retries)."""

    def __init__(
        self,
        settings: Settings,
        state_manager: StateManager,
        job_queue: JobQueueService,
        event_bus: Optional[DomainEventBus] = None,
    ):
        self.settings = settings
        self.state_manager = state_manager
        self.job_queue = job_queue
        self.event_bus = event_bus

    async def finalize_success(self, job: QueueJob, file_size: int) -> None:
        """Finalize successful job completion."""
        # Check the current status to avoid overwriting COMPLETED_DELETE_FAILED
        tracked_file = await self.state_manager.get_file_by_id(job.file_id)
        if tracked_file and tracked_file.status == FileStatus.COMPLETED_DELETE_FAILED:
            logging.debug(
                f"Skipping finalization for {job.file_path} as it already has delete error status"
            )
            await self.job_queue.mark_job_completed(job)
            return

        await self._finalize_job(
            job,
            status=FileStatus.COMPLETED,
            queue_action=self.job_queue.mark_job_completed,
            progress=100.0,
            error_message=None,
            log_message=f"Job completed successfully: {job.file_path}",
        )

    async def finalize_failure(self, job: QueueJob, error: Exception) -> None:
        """Finalize failed job with error handling."""
        error_message = str(error)
        await self._finalize_job(
            job,
            status=FileStatus.FAILED,
            queue_action=lambda j: self.job_queue.mark_job_failed(j, error_message),
            error_message=error_message,
            log_message=f"Job failed permanently: {job.file_path} - {error_message}",
            is_error=True,
        )

    async def finalize_max_retries(self, job: QueueJob) -> None:
        """Finalize job that failed after maximum retry attempts."""
        error_message = (
            f"Failed after {self.settings.max_retry_attempts} retry attempts"
        )
        await self._finalize_job(
            job,
            status=FileStatus.FAILED,
            queue_action=lambda j: self.job_queue.mark_job_failed(
                j, "Max retry attempts reached"
            ),
            error_message=error_message,
            log_message=f"Job failed after max retries: {job.file_path}",
            is_error=True,
        )

    async def _finalize_job(
        self,
        job: QueueJob,
        status: FileStatus,
        queue_action,
        progress: float = None,
        error_message: str = None,
        log_message: str = None,
        is_error: bool = False,
    ) -> None:
        """Common finalization logic for all job completion scenarios."""
        try:
            await queue_action(job)

            update_kwargs = {"error_message": error_message}
            if progress is not None:
                update_kwargs["copy_progress"] = progress
                update_kwargs["retry_count"] = 0

            await self.state_manager.update_file_status_by_id(
                job.file_id, status, **update_kwargs
            )

            if is_error:
                logging.error(log_message)
            else:
                logging.info(log_message)

        except Exception as e:
            logging.error(f"Error finalizing job {job.file_path}: {e}")

    def get_finalization_info(self) -> dict:
        """Get finalization service configuration details."""
        return {
            "max_retry_attempts": self.settings.max_retry_attempts,
            "state_manager_available": self.state_manager is not None,
            "job_queue_available": self.job_queue is not None,
        }
