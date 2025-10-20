"""
Job Finalization Service for File Transfer Agent.

Responsible solely for job completion workflows (success, failure, max retries).
Extracted from JobProcessor to follow Single Responsibility Principle.

This service handles:
- Successful job completion
- Failed job handling
- Maximum retry attempts handling
- Job queue and state manager updates
- Completion logging and error handling
"""

import logging
from typing import Dict

from app.config import Settings
from app.models import FileStatus
from app.services.state_manager import StateManager
from app.services.job_queue import JobQueueService
from app.services.consumer.job_models import QueueJob


class JobFinalizationService:
    """
    Responsible solely for job finalization workflows.

    This class adheres to SRP by handling only job completion concerns
    including success, failure, and retry limit scenarios.
    """

    def __init__(
        self,
        settings: Settings,
        state_manager: StateManager,
        job_queue: JobQueueService,
    ):
        """
        Initialize JobFinalizationService with required dependencies.

        Args:
            settings: Application settings for retry limits
            state_manager: Central state manager for file status updates
            job_queue: Job queue service for marking job completion status
        """
        self.settings = settings
        self.state_manager = state_manager
        self.job_queue = job_queue

        logging.debug("JobFinalizationService initialized")

    async def finalize_success(self, job: QueueJob, file_size: int) -> None:
        """
        Finalize successful job completion.

        Args:
            job: QueueJob object
            file_size: Final file size for statistics
        """
        file_path = job.file_path

        try:
            # Mark job as completed in queue
            await self.job_queue.mark_job_completed(job)

            # Update file status to completed - UUID precision via job
            await self.state_manager.update_file_status_by_id(
                job.file_id,  # Direct UUID access
                FileStatus.COMPLETED,
                copy_progress=100.0,
                error_message=None,
                retry_count=0,
            )

            logging.info(f"Job completed successfully: {file_path}")

        except Exception as e:
            logging.error(f"Error finalizing successful job {file_path}: {e}")

    async def finalize_failure(self, job: QueueJob, error: Exception) -> None:
        """
        Finalize failed job with error handling.

        Args:
            job: QueueJob object
            error: Exception that caused the failure
        """
        file_path = job.file_path
        error_message = str(error)

        try:
            # Mark job as failed in queue
            await self.job_queue.mark_job_failed(job, error_message)

            # Update file status to failed - UUID precision via job
            await self.state_manager.update_file_status_by_id(
                job.file_id,  # Direct UUID access
                FileStatus.FAILED,
                error_message=error_message
            )

            logging.error(f"Job failed permanently: {file_path} - {error_message}")

        except Exception as e:
            logging.error(f"Error finalizing failed job {file_path}: {e}")

    async def finalize_max_retries(self, job: QueueJob) -> None:
        """
        Finalize job that failed after maximum retry attempts.

        Args:
            job: QueueJob object
        """
        file_path = job.file_path
        error_message = (
            f"Failed after {self.settings.max_retry_attempts} retry attempts"
        )

        try:
            # Mark job as failed in queue
            await self.job_queue.mark_job_failed(job, "Max retry attempts reached")

            # Update file status to failed - UUID precision via job
            await self.state_manager.update_file_status_by_id(
                job.file_id,  # Direct UUID access
                FileStatus.FAILED,
                error_message=error_message
            )

            logging.error(f"Job failed after max retries: {file_path}")

        except Exception as e:
            logging.error(f"Error finalizing job after max retries {file_path}: {e}")

    def get_finalization_info(self) -> dict:
        """
        Get information about the finalization service configuration.

        Returns:
            Dictionary with finalization service configuration details
        """
        return {
            "max_retry_attempts": self.settings.max_retry_attempts,
            "state_manager_available": self.state_manager is not None,
            "job_queue_available": self.job_queue is not None,
        }
