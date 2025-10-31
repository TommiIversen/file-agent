"""
Job Space Manager - handles space checking and shortage workflows.
"""

import logging

from app.config import Settings
from app.models import FileStatus, SpaceCheckResult
from app.services.consumer.job_models import ProcessResult, QueueJob
from app.services.job_queue import JobQueueService
from app.core.file_repository import FileRepository
from app.core.events.event_bus import DomainEventBus
from app.core.events.file_events import FileStatusChangedEvent
from datetime import datetime


class JobSpaceManager:
    """Handles space checking and shortage workflows for job processing."""

    def __init__(
        self,
        settings: Settings,
        file_repository: FileRepository,
        event_bus: DomainEventBus,
        job_queue: JobQueueService,
        space_checker=None,
        space_retry_manager=None,
    ):
        self.settings = settings
        self.file_repository = file_repository
        self.event_bus = event_bus
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

        # Check if this is a network accessibility issue vs actual space shortage
        is_network_issue = "not accessible" in space_check.reason.lower()

        if is_network_issue:
            logging.warning(
                f"Network inaccessible for {file_path}: {space_check.reason}",
                extra={
                    "operation": "network_unavailable",
                    "file_path": file_path,
                    "reason": space_check.reason,
                },
            )

            # Update & Announce-mønsteret
            tracked_file = await self.file_repository.update_file_status(
                file_id=job.file_id,
                status=FileStatus.WAITING_FOR_NETWORK,
                error_message=f"Network unavailable: {space_check.reason}"
            )
            if tracked_file:
                await self.event_bus.publish(FileStatusChangedEvent(
                    file_id=tracked_file.id,
                    file_path=tracked_file.file_path,
                    old_status=job.tracked_file.status,
                    new_status=FileStatus.WAITING_FOR_NETWORK,
                    timestamp=datetime.now()
                ))

            return ProcessResult(
                success=False,
                file_path=file_path,
                error_message=f"Network unavailable: {space_check.reason}",
                should_retry=True,  # Should retry when network comes back
            )
        else:
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
            tracked_file = await self.file_repository.get_by_id(job.file_id)
            if tracked_file:
                tracked_file.status = FileStatus.FAILED
                tracked_file.error_message = f"Insufficient space: {space_check.reason}"
                await self.file_repository.update(tracked_file)

                if self.event_bus:
                    await self.event_bus.publish(FileStatusChangedEvent(
                        file_id=tracked_file.id,
                        file_path=tracked_file.file_path,
                        old_status=job.tracked_file.status,
                        new_status=FileStatus.FAILED,
                        timestamp=datetime.now()
                    ))
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
