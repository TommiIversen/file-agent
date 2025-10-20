"""
Job Space Manager - handles space checking and shortage workflows.
"""

import logging

from app.config import Settings
from app.models import FileStatus, SpaceCheckResult
from app.services.consumer.job_models import ProcessResult, QueueJob
from app.services.job_queue import JobQueueService
from app.services.state_manager import StateManager


class JobSpaceManager:
    """Handles space checking and shortage workflows for job processing."""

    def __init__(
            self,
            settings: Settings,
            state_manager: StateManager,
            job_queue: JobQueueService,
            space_checker=None,
            space_retry_manager=None,
    ):
        self.settings = settings
        self.state_manager = state_manager
        self.job_queue = job_queue
        self.space_checker = space_checker
        self.space_retry_manager = space_retry_manager

        logging.debug("JobSpaceManager initialized")

    def should_check_space(self) -> bool:
        """Check if space checking should be performed."""
        return (
                self.settings.enable_pre_copy_space_check and self.space_checker is not None
        )

    async def check_space_for_job(self, job: QueueJob) -> SpaceCheckResult:
        """Perform space check for a job."""
        if not self.space_checker:
            file_size = job.file_size
            return SpaceCheckResult(
                has_space=True,
                available_bytes=0,
                required_bytes=file_size,
                file_size_bytes=file_size,
                safety_margin_bytes=0,
                reason="No space checker configured",
            )

        file_size = job.tracked_file.file_size
        return self.space_checker.check_space_for_file(file_size)

    async def handle_space_shortage(
            self, job: QueueJob, space_check: SpaceCheckResult
    ) -> ProcessResult:
        """Handle space shortage by scheduling retry or marking as failed."""
        file_path = job.file_path

        logging.warning(
            f"Insufficient space for {file_path}: {space_check.reason}",
            extra={
                "operation": "space_shortage",
                "file_path": file_path,
                "available_gb": space_check.get_available_gb(),
                "required_gb": space_check.get_required_gb(),
                "shortage_gb": space_check.get_shortage_gb(),
            },
        )

        if self.space_retry_manager:
            try:
                await self.space_retry_manager.schedule_space_retry(
                    job.tracked_file, space_check
                )
                return ProcessResult(
                    success=False,
                    file_path=file_path,
                    error_message=f"Insufficient space: {space_check.reason}",
                    retry_scheduled=True,
                    space_shortage=True,
                )
            except Exception as e:
                logging.error(f"Error scheduling space retry for {file_path}: {e}")

        try:
            await self.state_manager.update_file_status_by_id(
                job.file_id,
                FileStatus.FAILED,
                error_message=f"Insufficient space: {space_check.reason}",
            )
            await self.job_queue.mark_job_failed(job, "Insufficient disk space")
        except Exception as e:
            logging.error(
                f"Error marking job as failed due to space shortage {file_path}: {e}"
            )

        return ProcessResult(
            success=False,
            file_path=file_path,
            error_message=f"Insufficient space: {space_check.reason}",
            space_shortage=True,
        )

    def get_space_manager_info(self) -> dict:
        """Get information about the space manager configuration."""
        return {
            "space_checking_enabled": self.should_check_space(),
            "space_checker_available": self.space_checker is not None,
            "space_retry_manager_available": self.space_retry_manager is not None,
            "pre_copy_space_check_setting": self.settings.enable_pre_copy_space_check,
        }
