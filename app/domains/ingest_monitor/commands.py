"""
Ingest Monitor Commands

This module defines commands for performing actions on ingest monitor data
following the CQRS pattern.
"""

from dataclasses import dataclass
from app.core.cqrs.command import Command


@dataclass
class ClearAllChannelErrorsCommand(Command):
    """
    Command to clear errors for all channels.
    
    This command will:
    1. Clear errors on Just In Engine for all active channels
    2. Update local state cache to reflect cleared errors
    3. Publish events to update UI
    """
    pass  # No parameters needed - operates on all channels


@dataclass
class StartAllChannelsCommand(Command):
    """
    Command to start all channels.
    
    This command will:
    1. Start all active channels on Just In Engine
    2. Update local state cache to reflect started channels
    3. Publish events to update UI
    """
    pass  # No parameters needed - operates on all channels


@dataclass
class StopAllChannelsCommand(Command):
    """
    Command to stop all channels.
    
    This command will:
    1. Stop all active channels on Just In Engine
    2. Update local state cache to reflect stopped channels
    3. Publish events to update UI
    """
    pass  # No parameters needed - operates on all channels