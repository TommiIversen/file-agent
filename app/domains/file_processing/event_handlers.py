"""
Event Handlers for File Processing Domain.

These handlers listen to domain events and orchestrate workflow initiation
by sending appropriate commands via the command bus.
"""
import logging
from app.core.cqrs.command_bus import CommandBus
from app.core.events.file_events import FileReadyEvent
from app.core.file_repository import FileRepository
from app.domains.file_processing.commands import QueueFileCommand


class FileProcessingEventHandler:
    """
    Listens to domain events and initiates file processing workflows.
    
    This handler acts as the bridge between the event-driven file discovery
    and the command-driven file processing workflow. It maintains SRP by
    only handling event-to-command translation.
    """
    
    def __init__(self, command_bus: CommandBus, file_repository: FileRepository):
        self._command_bus = command_bus
        self._file_repository = file_repository

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