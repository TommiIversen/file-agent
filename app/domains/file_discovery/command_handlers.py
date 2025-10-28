"""
File Discovery Command Handlers
Handles commands related to file discovery operations.
"""
from app.core.cqrs.command import CommandHandler
from app.domains.file_discovery.commands import (
    AddFileCommand, 
    MarkFileReadyCommand, 
    MarkFileStableCommand,
    UpdateFileGrowthInfoCommand,
    MarkFileGrowingCommand,
    MarkFileReadyToStartGrowingCommand
)
from app.domains.file_discovery.file_discovery_slice import FileDiscoverySlice
from app.models import TrackedFile


class AddFileCommandHandler(CommandHandler[AddFileCommand, TrackedFile]):
    """Handles AddFileCommand by adding a discovered file to the system."""

    def __init__(self, file_discovery_slice: FileDiscoverySlice):
        self._file_discovery_slice = file_discovery_slice

    async def handle(self, command: AddFileCommand) -> TrackedFile:
        """Add a newly discovered file to the system."""
        return await self._file_discovery_slice.add_discovered_file(
            file_path=command.file_path,
            file_size=command.file_size,
            last_write_time=command.last_write_time
        )


class MarkFileReadyCommandHandler(CommandHandler[MarkFileReadyCommand, bool]):
    """Handles MarkFileReadyCommand by marking a file as ready for processing."""

    def __init__(self, file_discovery_slice: FileDiscoverySlice):
        self._file_discovery_slice = file_discovery_slice

    async def handle(self, command: MarkFileReadyCommand) -> bool:
        """Mark a file as ready for processing."""
        return await self._file_discovery_slice.mark_file_ready(command.file_id)


class MarkFileStableCommandHandler(CommandHandler[MarkFileStableCommand, bool]):
    """Handles MarkFileStableCommand by marking a file as stable."""

    def __init__(self, file_discovery_slice: FileDiscoverySlice):
        self._file_discovery_slice = file_discovery_slice

    async def handle(self, command: MarkFileStableCommand) -> bool:
        """Mark a file as stable (ready for processing)."""
        # For now, we'll use the existing mark_file_ready logic
        # In future, we might want separate stable vs ready states
        return await self._file_discovery_slice.mark_file_ready(command.file_id)


class UpdateFileGrowthInfoCommandHandler(CommandHandler[UpdateFileGrowthInfoCommand, bool]):
    """Handles UpdateFileGrowthInfoCommand by updating file growth information."""

    def __init__(self, file_discovery_slice: FileDiscoverySlice):
        self._file_discovery_slice = file_discovery_slice

    async def handle(self, command: UpdateFileGrowthInfoCommand) -> bool:
        """Update file growth information."""
        return await self._file_discovery_slice.update_file_growth_info(
            file_id=command.file_id,
            file_size=command.file_size,
            previous_file_size=command.previous_file_size,
            growth_rate_mbps=command.growth_rate_mbps,
            growth_stable_since=command.growth_stable_since,
            last_growth_check=command.last_growth_check
        )


class MarkFileGrowingCommandHandler(CommandHandler[MarkFileGrowingCommand, bool]):
    """Handles MarkFileGrowingCommand by marking a file as growing."""

    def __init__(self, file_discovery_slice: FileDiscoverySlice):
        self._file_discovery_slice = file_discovery_slice

    async def handle(self, command: MarkFileGrowingCommand) -> bool:
        """Mark a file as growing."""
        return await self._file_discovery_slice.mark_file_growing(command.file_id)


class MarkFileReadyToStartGrowingCommandHandler(CommandHandler[MarkFileReadyToStartGrowingCommand, bool]):
    """Handles MarkFileReadyToStartGrowingCommand by marking a file as ready to start growing copy."""

    def __init__(self, file_discovery_slice: FileDiscoverySlice):
        self._file_discovery_slice = file_discovery_slice

    async def handle(self, command: MarkFileReadyToStartGrowingCommand) -> bool:
        """Mark a file as ready to start growing copy."""
        return await self._file_discovery_slice.mark_file_ready_to_start_growing(command.file_id)