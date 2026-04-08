"""
Job Space Manager - handles space checking and shortage workflows.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from app.config import Settings
from app.models import FileStatus, SpaceCheckResult
from app.domains.file_processing.consumer.job_models import ProcessResult, QueueJob
from app.core.file_repository import FileRepository
from app.core.file_state_machine import FileStateMachine
from app.core.events.event_bus import DomainEventBus
from app.core.events.file_events import FileCopyFailedEvent
from app.core.exceptions import InvalidTransitionError
from app.domains.file_processing.space_checker import SpaceChecker
from app.domains.file_processing.space_retry_manager import SpaceRetryManager


class JobSpaceManager:
    """Handles space checking and shortage workflows for job processing."""

    def __init__(
        self,
        settings: Settings,
        file_repository: FileRepository,
        space_checker: Optional[SpaceChecker],
        state_machine: FileStateMachine,
        retry_manager: Optional[SpaceRetryManager],
        event_bus: DomainEventBus,
    ):
        self.settings = settings
        self.file_repository = file_repository
        self.space_checker = space_checker
        self.state_machine = state_machine
        self.retry_manager = retry_manager
        self.event_bus = event_bus
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

        file_size = job.file_size
        return self.space_checker.check_space_for_file(file_size)

    async def handle_space_shortage(
        self, job: QueueJob, space_check: SpaceCheckResult
    ) -> ProcessResult:
        """Handle space shortage by scheduling retry or marking as failed."""
        file_path = job.file_path

        tracked_file = await self.file_repository.get_by_id(job.file_id)
        if not tracked_file:
            raise ValueError(
                f"TrackedFile not found for file_id={job.file_id} in handle_space_shortage"
            )

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

            try:
                await self.state_machine.transition(
                    file_id=job.file_id,
                    new_status=FileStatus.WAITING_FOR_NETWORK,
                    error_message=f"Network unavailable: {space_check.reason}"
                )
            except InvalidTransitionError as e:
                logging.warning(f"Could not transition {job.file_id} to WAITING_FOR_NETWORK: {e}")

            return ProcessResult(
                success=False,
                file_path=file_path,
                error_message=f"Network unavailable: {space_check.reason}",
                should_retry=True,
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

            if self.retry_manager:
                try:
                    await self.retry_manager.schedule_space_retry(
                        tracked_file, space_check
                    )
                    return ProcessResult(
                        success=False,
                        file_path=file_path,
                        error_message=f"Insufficient space: {space_check.reason}",
                        retry_scheduled=True,
                        space_shortage=True,
                    )
                except Exception as e:
                    logging.error(f"Error scheduling space retry for {file_path}: {e}", exc_info=True)

        error_msg = f"Insufficient space: {space_check.reason}"
        try:
            await self.state_machine.transition(
                file_id=tracked_file.id,
                new_status=FileStatus.FAILED,
                error_message=error_msg,
                failed_at=datetime.now(timezone.utc),
            )
            await self.event_bus.publish(FileCopyFailedEvent(
                file_id=tracked_file.id,
                file_path=file_path,
                error_message=error_msg,
            ))
        except InvalidTransitionError as e:
            logging.warning(
                f"Could not transition {tracked_file.id} to FAILED: {e}"
            )

        return ProcessResult(
            success=False,
            file_path=file_path,
            error_message=error_msg,
            space_shortage=True,
        )

    def get_space_manager_info(self) -> dict:
        """Get information about the space manager configuration."""
        return {
            "space_checking_enabled": self.should_check_space(),
            "space_checker_available": self.space_checker is not None,
            "space_retry_manager_available": self.retry_manager is not None,
            "pre_copy_space_check_setting": self.settings.enable_pre_copy_space_check,
        }
