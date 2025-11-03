"""
Lifecycle Domain Commands
Commands for managing the lifecycle of tracked files.
"""
from dataclasses import dataclass

from app.core.cqrs.command import Command


@dataclass
class PruneOldFilesCommand(Command):
    """
    Command to delete old, terminal files from repository.
    
    This command is responsible solely for identifying and removing
    old files that have reached terminal states and are older than
    the specified retention period.
    """
    hours_to_keep: int