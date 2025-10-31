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
from app.core.file_repository import FileRepository
from app.core.events.file_events import FileStatusChangedEvent, FileCopyCompletedEvent
from datetime import datetime


class JobFinalizationService:
    """Handles job completion workflows (success, failure, max retries)."""

    def __init__(
        self,
        settings: Settings,
        file_repository: FileRepository,
        job_queue: JobQueueService,
        event_bus: Optional[DomainEventBus] = None,
    ):
        self.settings = settings
        self.file_repository = file_repository
        self.job_queue = job_queue
        self.event_bus = event_bus

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
            await self.job_queue.mark_job_completed(job)
            return

        await self.job_queue.mark_job_completed(job)
        tracked_file.status = FileStatus.COMPLETED
        tracked_file.completed_at = datetime.now()
        tracked_file.copy_progress = 100.0
        tracked_file.error_message = None
        await self.file_repository.update(tracked_file)
        await self.event_bus.publish(FileStatusChangedEvent(
            file_id=tracked_file.id,
            file_path=tracked_file.file_path,
            old_status=tracked_file.status,
            new_status=FileStatus.COMPLETED,
            timestamp=datetime.now()
        ))
        await self.event_bus.publish(FileCopyCompletedEvent(
            file_id=tracked_file.id,
            file_path=tracked_file.file_path,
            destination_path=getattr(tracked_file, "destination_path", None),
            bytes_copied=tracked_file.file_size
        ))
        logging.info(f"Job completed successfully: {job.file_path}")

    async def finalize_failure(self, job: QueueJob, error: Exception) -> None:
        """Finalize failed job with error handling."""
        error_message = str(error)
        await self.job_queue.mark_job_failed(job, error_message)

        tracked_file = await self.file_repository.get_by_id(job.file_id)
        if not tracked_file:
            logging.warning(f"Tracked file not found for job {job.file_path} in finalize_failure")
            return
        tracked_file.status = FileStatus.FAILED
        tracked_file.error_message = error_message
        await self.file_repository.update(tracked_file)
        await self.event_bus.publish(FileStatusChangedEvent(
            file_id=tracked_file.id,
            file_path=tracked_file.file_path,
            old_status=tracked_file.status,
            new_status=FileStatus.FAILED,
            timestamp=datetime.now()
        ))

    async def finalize_max_retries(self, job: QueueJob) -> None:
        """Finalize job that failed after maximum retry attempts."""
        error_message = (
            f"Failed after {self.settings.max_retry_attempts} retry attempts"
        )
        await self.job_queue.mark_job_failed(job, "Max retry attempts reached")

        tracked_file = await self.file_repository.get_by_id(job.file_id)
        if not tracked_file:
            logging.warning(f"Tracked file not found for job {job.file_path} in finalize_max_retries")
            return
        tracked_file.status = FileStatus.FAILED
        tracked_file.error_message = error_message
        await self.file_repository.update(tracked_file)
        await self.event_bus.publish(FileStatusChangedEvent(
            file_id=tracked_file.id,
            file_path=tracked_file.file_path,
            old_status=tracked_file.status,
            new_status=FileStatus.FAILED,
            timestamp=datetime.now()
        ))
        logging.error(f"Job failed after max retries: {job.file_path}")

    def get_finalization_info(self) -> dict:
        """Get finalization service configuration details."""
        return {
            "max_retry_attempts": self.settings.max_retry_attempts,
            "file_repository_available": self.file_repository is not None,
            "job_queue_available": self.job_queue is not None,
        }
