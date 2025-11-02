"""
Event Handlers for File Processing Domain.

These handlers listen to domain events and orchestrate workflow initiation
by sending appropriate commands via the command bus.
"""
import logging
from app.core.cqrs.command_bus import CommandBus
from app.core.events.file_events import FileReadyEvent
from app.core.events.storage_events import DestinationUnavailableEvent, DestinationRecoveredEvent
from app.core.file_repository import FileRepository
from app.domains.file_processing.commands import QueueFileCommand
from app.domains.file_processing.job_queue import JobQueueService


class FileProcessingEventHandler:
    """
    Listens to domain events and initiates file processing workflows.
    
    This handler acts as the bridge between the event-driven file discovery
    and the command-driven file processing workflow. It maintains SRP by
    only handling event-to-command translation.
    """
    
    def __init__(
        self, 
        command_bus: CommandBus, 
        file_repository: FileRepository, 
        job_queue_service: JobQueueService
    ):
        self._command_bus = command_bus
        self._file_repository = file_repository
        self._job_queue_service = job_queue_service

    async def handle_file_ready(self, event: FileReadyEvent):
        """
        Handles FileReadyEvent and sends a command to queue the file.
        
        This method translates the domain event into a command, ensuring
        the separation between event notification and command execution.
        """
        logging.debug(f"FileReadyEventHandler received event for: {event.file_path}")

        # Fetch the complete, fresh object from repository
        tracked_file = await self._file_repository.get_by_id(event.file_id)
        if not tracked_file:
            logging.warning(f"FileReadyEventHandler: File {event.file_id} not found.")
            return

        # Send command to queue the file
        command = QueueFileCommand(tracked_file=tracked_file)
        await self._command_bus.execute(command)

    async def handle_destination_unavailable(self, event: DestinationUnavailableEvent):
        """
        Handles DestinationUnavailableEvent by pausing file processing operations.
        
        This method receives storage unavailable events and pauses the job queue
        to prevent failed copy attempts.
        """
        logging.info(f"Handling destination unavailable: {event.reason}")
        
        try:
            await self._job_queue_service.handle_destination_unavailable()
            logging.info("⏸️ Operations paused successfully due to destination unavailable")
        except Exception as e:
            logging.error(f"Error pausing operations: {e}")

    async def handle_destination_recovered(self, event: DestinationRecoveredEvent):
        """
        Handles DestinationRecoveredEvent by resuming file processing operations.
        
        This method receives storage recovery events and resumes the job queue
        to continue processing waiting files.
        """
        logging.info(f"Handling destination recovery: {event.reason}")
        
        try:
            await self._job_queue_service.process_waiting_network_files()
            logging.info("✅ Operations resumed successfully after destination recovery")
        except Exception as e:
            logging.error(f"Error resuming operations: {e}")