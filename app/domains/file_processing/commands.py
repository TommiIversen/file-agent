"""
Commands for File Processing Domain.

Following CQRS pattern, these commands represent intent to perform operations
within the file processing domain.
"""
from dataclasses import dataclass
from app.core.cqrs.command import Command
from app.models import TrackedFile
from app.domains.file_processing.consumer.job_models import QueueJob


@dataclass
class QueueFileCommand(Command):
    """
    Command to queue a file for processing.
    
    This command encapsulates the intent to add a TrackedFile to the processing queue.
    The command handler will validate the file state and perform the queueing operation.
    """
    tracked_file: TrackedFile


@dataclass  
class ProcessJobCommand(Command):
    """
    Command to process a single job from the queue.
    
    This command encapsulates the intent to execute all processing steps for a job,
    including space checking, file preparation, copying, and finalization.
    """
    job: QueueJob