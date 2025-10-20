"""
Job Space Manager Service for File Transfer Agent.

Responsible solely for space checking and space shortage handling workflows.
Extracted from JobProcessor to follow Single Responsibility Principle.

This service handles:
- Pre-flight space checking for jobs
- Space shortage detection and response
- Integration with SpaceRetryManager for retry scheduling
- Space-related error handling and logging
"""

import logging
from typing import Dict

from app.config import Settings
from app.models import FileStatus, SpaceCheckResult
from app.services.state_manager import StateManager
from app.services.job_queue import JobQueueService
from app.services.consumer.job_models import ProcessResult


class JobSpaceManager:
    """
    Responsible solely for space checking and space shortage handling.

    This class adheres to SRP by handling only space-related concerns
    for job processing workflows.
    """

    def __init__(
        self,
        settings: Settings,
        state_manager: StateManager,
        job_queue: JobQueueService,
        space_checker=None,
        space_retry_manager=None,
    ):
        """
        Initialize JobSpaceManager with required dependencies.

        Args:
            settings: Application settings for space checking configuration
            state_manager: Central state manager for file status updates
            job_queue: Job queue service for marking failed jobs
            space_checker: Optional space checking utility
            space_retry_manager: Optional space retry manager for scheduling retries
        """
        self.settings = settings
        self.state_manager = state_manager
        self.job_queue = job_queue
        self.space_checker = space_checker
        self.space_retry_manager = space_retry_manager

        logging.debug("JobSpaceManager initialized")

    def should_check_space(self) -> bool:
        """
        Check if space checking should be performed.

        Returns:
            True if space checking is enabled and space checker is available
        """
        return (
            self.settings.enable_pre_copy_space_check and self.space_checker is not None
        )

    async def check_space_for_job(self, job: Dict) -> SpaceCheckResult:
        """
        Perform space check for a job.

        Args:
            job: Job dictionary containing file info

        Returns:
            SpaceCheckResult with space availability information
        """
        if not self.space_checker:
            # If no space checker available, assume space is available
            file_size = job.get("file_size", 0)
            return SpaceCheckResult(
                has_space=True,
                available_bytes=0,  # Unknown when no checker
                required_bytes=file_size,
                file_size_bytes=file_size,
                safety_margin_bytes=0,
                reason="No space checker configured",
            )

        # Get file size from job or tracked file
        file_size = job.get("file_size", 0)

        if file_size == 0:
            # Fallback: get from tracked file
            tracked_file = await self.state_manager.get_file_by_path(job["file_path"])
            if tracked_file:
                file_size = tracked_file.file_size

        return self.space_checker.check_space_for_file(file_size)

    async def handle_space_shortage(
        self, job: Dict, space_check: SpaceCheckResult
    ) -> ProcessResult:
        """
        Handle space shortage by scheduling retry or marking as failed.

        Args:
            job: Job that couldn't be processed due to space
            space_check: Result of space check

        Returns:
            ProcessResult indicating space shortage handling outcome
        """
        file_path = job["file_path"]

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

        # Use SpaceRetryManager if available, otherwise mark as failed
        if self.space_retry_manager:
            try:
                await self.space_retry_manager.schedule_space_retry(
                    file_path, space_check
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

        # Fallback: mark as failed if no retry manager or retry scheduling failed - UUID precision
        try:
            tracked_file = await self.state_manager.get_file_by_path(file_path)
            if tracked_file:
                await self.state_manager.update_file_status_by_id(
                    tracked_file.id,
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
        """
        Get information about the space manager configuration.

        Returns:
            Dictionary with space manager configuration details
        """
        return {
            "space_checking_enabled": self.should_check_space(),
            "space_checker_available": self.space_checker is not None,
            "space_retry_manager_available": self.space_retry_manager is not None,
            "pre_copy_space_check_setting": self.settings.enable_pre_copy_space_check,
        }
