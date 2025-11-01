"""
Command Handlers for File Processing Domain.

These handlers contain the business logic for executing commands within
the file processing domain. Each handler has a single responsibility
and maintains clean dependencies following the inward flow mandate.
"""
import logging
from datetime import datetime
from app.core.file_repository import FileRepository
from app.core.file_state_machine import FileStateMachine
from app.core.exceptions import InvalidTransitionError
from app.models import FileStatus, StorageStatus
from app.domains.file_processing.consumer.job_models import QueueJob
from app.domains.file_processing.copy.growing_copy import GrowingFileCopyStrategy
from app.domains.file_processing.commands import QueueFileCommand, ProcessJobCommand


class QueueFileCommandHandler:
    """
    Handles the logic for validating and adding a file to the job queue.
    
    This handler combines the validation logic from JobQueueService.handle_file_ready
    and the queue addition logic from _add_job_to_queue, maintaining SRP by
    focusing solely on the file queueing workflow.
    """
    
    def __init__(
        self,
        job_queue_service,  # Pass the service instead of the queue directly
        file_repository: FileRepository,
        state_machine: FileStateMachine,
        storage_monitor,
        copy_strategy: GrowingFileCopyStrategy,
    ):
        self._job_queue_service = job_queue_service
        self._file_repository = file_repository
        self._state_machine = state_machine
        self._storage_monitor = storage_monitor
        self._copy_strategy = copy_strategy

    async def handle(self, command: QueueFileCommand):
        """
        Executes the logic from JobQueueService.handle_file_ready + _add_job_to_queue.
        
        This method validates the file state, checks network availability,
        and adds the job to the queue if all conditions are met.
        """
        tracked_file = command.tracked_file

        # --- Logic from handle_file_ready ---
        if tracked_file.status not in [FileStatus.READY, FileStatus.READY_TO_START_GROWING]:
            logging.warning(
                f"Ignoring QueueFileCommand for {tracked_file.file_path} "
                f"(status: {tracked_file.status.value})"
            )
            return

        if not await self._is_network_available():
            try:
                await self._state_machine.transition(
                    file_id=tracked_file.id,
                    new_status=FileStatus.WAITING_FOR_NETWORK,
                    error_message="Network unavailable - waiting for recovery"
                )
            except (InvalidTransitionError, ValueError) as e:
                logging.warning(
                    f"Could not set file {tracked_file.id} to WAITING_FOR_NETWORK: {e}"
                )
            return

        # --- Logic from _add_job_to_queue ---
        try:
            is_growing = (
                tracked_file.status == FileStatus.READY_TO_START_GROWING or 
                self._copy_strategy._is_file_currently_growing(tracked_file)
            )

            job = QueueJob(
                file_id=tracked_file.id,
                file_path=tracked_file.file_path,
                file_size=tracked_file.file_size,
                creation_time=tracked_file.creation_time,
                is_growing_at_queue_time=is_growing,
                added_to_queue_at=datetime.now(),
                retry_count=0,
            )

            # Transition state BEFORE adding to queue
            await self._state_machine.transition(
                file_id=tracked_file.id,
                new_status=FileStatus.IN_QUEUE
            )

            # Get queue from service and add job
            queue = self._job_queue_service.get_queue()
            if queue is None:
                logging.error("Queue is not initialized yet!")
                return
                
            await queue.put(job)
            logging.info(f"Job added to queue: {job}")

        except InvalidTransitionError as e:
            logging.warning(f"Could not add job to queue (state conflict): {e}")
        except Exception as e:
            logging.error(f"Error adding to queue: {e}")

    async def _is_network_available(self) -> bool:
        """
        Check if destination network is available.
        
        Moved from JobQueueService to maintain encapsulation of network checking logic.
        """
        if not self._storage_monitor:
            return True  # Assume available if no storage monitor

        try:
            storage_state = self._storage_monitor._storage_state
            dest_info = storage_state.get_destination_info()

            if not dest_info:
                return False  # No destination info = not available

            # Available if status is OK or WARNING (WARNING still allows copying)
            return dest_info.status in [StorageStatus.OK, StorageStatus.WARNING]

        except Exception as e:
            logging.error(f"Error checking network availability: {e}")
            return True  # Default to available on error


class ProcessJobCommandHandler:
    """
    Handles the complete logic for processing a single job.
    
    This handler will be implemented in Phase 3 to orchestrate the job processing
    workflow using the existing sub-services (space manager, file preparation, etc.).
    """
    
    def __init__(self):
        # Implementation will be added in Phase 3
        pass

    async def handle(self, command: ProcessJobCommand):
        """
        Will execute the logic from JobProcessor.process_job.
        
        Implementation will be added in Phase 3 of the refactoring plan.
        """
        # To be implemented in Phase 3
        raise NotImplementedError("ProcessJobCommandHandler will be implemented in Phase 3")