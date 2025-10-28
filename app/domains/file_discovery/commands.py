"""
File Discovery Domain Commands
Commands that modify state related to file discovery operations.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.core.cqrs.command import Command


@dataclass
class AddFileCommand(Command):
    """Command to add a newly discovered file to the system."""
    file_path: str
    file_size: int
    last_write_time: Optional[datetime] = None


@dataclass
class MarkFileReadyCommand(Command):
    """Command to mark a file as ready for processing."""
    file_id: str


@dataclass
class MarkFileStableCommand(Command):
    """Command to mark a file as stable (no longer growing)."""
    file_id: str
    file_path: str


@dataclass
class UpdateFileGrowthInfoCommand(Command):
    """Command to update file growth information."""
    file_id: str
    file_size: int
    previous_file_size: Optional[int] = None
    growth_rate_mbps: Optional[float] = None
    growth_stable_since: Optional[datetime] = None
    last_growth_check: Optional[datetime] = None


@dataclass
class MarkFileGrowingCommand(Command):
    """Command to mark a file as growing."""
    file_id: str
    file_path: str


@dataclass
class MarkFileReadyToStartGrowingCommand(Command):
    """Command to mark a file as ready to start growing copy."""
    file_id: str
    file_path: str