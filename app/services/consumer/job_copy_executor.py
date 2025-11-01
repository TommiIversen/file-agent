from app.core.events.file_events import FileCopyStartedEvent, FileCopyFailedEvent
from app.core.file_state_machine import FileStateMachine
from app.core.exceptions import InvalidTransitionError


import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import Settings
from app.core.events.event_bus import DomainEventBus
from app.models import FileStatus
from app.services.consumer.job_error_classifier import JobErrorClassifier
from app.services.consumer.job_models import PreparedFile
from app.services.copy.network_error_detector import NetworkError
from app.services.copy.exceptions import FileCopyError
from app.services.copy.growing_copy import GrowingFileCopyStrategy
from app.core.file_repository import FileRepository



class JobCopyExecutor:
    """Executes copy operations with status management and intelligent error handling."""

    def __init__(
        self,
        settings: Settings,
        file_repository: FileRepository,
        copy_strategy: GrowingFileCopyStrategy,
        state_machine: FileStateMachine,  # <-- TILFØJ DENNE
        error_classifier: Optional[JobErrorClassifier] = None,
        event_bus: Optional[DomainEventBus] = None,
    ):
        self.settings = settings
        self.file_repository = file_repository
        self.copy_strategy = copy_strategy
        self._state_machine = state_machine  # <-- TILFØJ DENNE
        self.error_classifier = error_classifier
        self.event_bus = event_bus

    async def initialize_copy_status(self, prepared_file: PreparedFile) -> None:
        """Initialize file status for copying operation and publish event."""
        new_status = prepared_file.initial_status

        # Use state machine for status transition
        try:
            await self._state_machine.transition(
                file_id=prepared_file.job.file_id,
                new_status=new_status,
                # kwargs til at sætte data:
                copy_progress=0.0,
                started_copying_at=datetime.now()
            )

            # Publicer den domæne-specifikke event (StateMachine publicerer StatusChanged)
            if self.event_bus:
                await self.event_bus.publish(
                    FileCopyStartedEvent(
                        file_id=prepared_file.job.file_id,
                        file_path=prepared_file.job.file_path,
                        destination_path=str(prepared_file.destination_path)
                    )
                )
        except (InvalidTransitionError, ValueError) as e:
            logging.warning(f"Kunne ikke initialisere kopi-status for {prepared_file.job.file_id}: {e}")
    async def execute_copy(self, prepared_file: PreparedFile) -> bool:
        """Execute copy operation using the selected strategy."""
        try:
            source_path = Path(prepared_file.job.file_path)
            dest_path = Path(str(prepared_file.destination_path))

            tracked_file_for_copy = await self.file_repository.get_by_id(prepared_file.job.file_id)
            if not tracked_file_for_copy:
                logging.warning(f"TrackedFile not found for job ID: {prepared_file.job.file_id} during copy execution.")
                return False

            copy_success = await self.copy_strategy.copy_file(
                str(source_path),
                str(dest_path),
                tracked_file_for_copy,
            )

            self._log_copy_result(prepared_file, copy_success)
            return copy_success

        except FileNotFoundError:
            # Let FileNotFoundError bubble up to be handled by error classifier
            raise
        except NetworkError:
            # Let NetworkError bubble up to be handled by error classifier
            raise
        except Exception as e:
            logging.error(
                f"Unexpected error during copy execution for {Path(prepared_file.job.file_path).name}: {e}"
            )
            raise FileCopyError(f"Unexpected error during copy execution: {e}") from e


    def _log_copy_result(self, prepared_file, success: bool):
        """Log copy operation result."""
        file_name = Path(prepared_file.job.file_path).name

        if success:
            logging.info(f"Copy completed: {file_name}")
        else:
            logging.error(f"Copy failed: {file_name}")

    async def handle_copy_failure(
        self, prepared_file: PreparedFile, error: Exception
    ) -> bool:
        """Handle copy failure with intelligent error classification."""
        if not self.error_classifier:
            await self._handle_fail_error(prepared_file, "Copy operation failed", error)
            return False

        status, reason = self.error_classifier.classify_copy_error(
            error, prepared_file.job.file_path
        )

        if status == FileStatus.REMOVED:
            await self._handle_remove_error(prepared_file, reason, error)
            return False  # File is gone, don't retry
        else:  # FileStatus.FAILED
            await self._handle_fail_error(prepared_file, reason, error)
            return False

    async def _handle_remove_error(
        self, prepared_file: PreparedFile, reason: str, error: Exception
    ) -> None:
        """Handle errors where source file disappeared."""
        try:
            await self._state_machine.transition(
                file_id=prepared_file.job.file_id,
                new_status=FileStatus.REMOVED,
                # kwargs til at sætte data:
                copy_progress=0.0,
                bytes_copied=0,
                error_message=f"Removed: {reason}"
            )

            # Publicer den domæne-specifikke event
            if self.event_bus:
                await self.event_bus.publish(
                    FileCopyFailedEvent(
                        file_id=prepared_file.job.file_id,
                        file_path=prepared_file.job.file_path,
                        error_message=f"Removed: {reason}"
                    )
                )

            file_name = Path(prepared_file.job.file_path).name
            logging.info(f"File removed during copy: {file_name} - {reason}")

        except (InvalidTransitionError, ValueError) as e:
            logging.warning(f"Kunne ikke sætte fil {prepared_file.job.file_id} til REMOVED: {e}")

    async def _handle_fail_error(
        self, prepared_file: PreparedFile, reason: str, error: Exception
    ) -> None:
        """Handle errors that should result in immediate failure."""
        try:
            await self._state_machine.transition(
                file_id=prepared_file.job.file_id,
                new_status=FileStatus.FAILED,
                # kwargs til at sætte data:
                copy_progress=0.0,
                bytes_copied=0,
                error_message=f"Failed: {reason}",
                failed_at=datetime.now()  # StateMachine sætter også dette, men eksplicit er ok
            )

            # Publicer den domæne-specifikke event
            if self.event_bus:
                await self.event_bus.publish(
                    FileCopyFailedEvent(
                        file_id=prepared_file.job.file_id,
                        file_path=prepared_file.job.file_path,
                        error_message=f"Failed: {reason}"
                    )
                )

            file_name = Path(prepared_file.job.file_path).name
            logging.error(f"Copy failed: {file_name} - {reason}")

        except (InvalidTransitionError, ValueError) as e:
            logging.warning(f"Kunne ikke sætte fil {prepared_file.job.file_id} til FAILED: {e}")

    def get_copy_executor_info(self) -> dict:
        """Get copy executor configuration details."""
        return {
            "copy_strategy": self.copy_strategy.__class__.__name__,
            "file_repository_available": self.file_repository is not None,
        }