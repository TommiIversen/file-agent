from app.core.cqrs.command_bus import CommandBus
from app.core.cqrs.query_bus import QueryBus
from app.domains.file_discovery.command_handlers import (
    AddFileCommandHandler,
    MarkFileReadyCommandHandler,
    MarkFileStableCommandHandler,
    UpdateFileGrowthInfoCommandHandler,
    MarkFileGrowingCommandHandler,
    MarkFileReadyToStartGrowingCommandHandler
)
from app.domains.file_discovery.commands import (
    AddFileCommand,
    MarkFileReadyCommand,
    MarkFileStableCommand,
    UpdateFileGrowthInfoCommand,
    MarkFileGrowingCommand,
    MarkFileReadyToStartGrowingCommand
)
from app.domains.file_discovery.file_discovery_slice import FileDiscoverySlice
from app.domains.file_discovery.queries import (
    GetActiveFileByPathQuery,
    ShouldSkipFileProcessingQuery,
    GetCurrentFileForPathQuery,
    GetFilesByStatusQuery,
    GetFilesNeedingGrowthMonitoringQuery
)
from app.domains.file_discovery.query_handlers import (
    GetActiveFileByPathQueryHandler,
    ShouldSkipFileProcessingQueryHandler,
    GetCurrentFileForPathQueryHandler,
    GetFilesByStatusQueryHandler,
    GetFilesNeedingGrowthMonitoringQueryHandler
)


def register_file_discovery_handlers(
    command_bus: CommandBus,
    query_bus: QueryBus,
    file_discovery_slice: FileDiscoverySlice
):
    """Register all File Discovery CQRS handlers."""
    command_bus.register(AddFileCommand, AddFileCommandHandler(file_discovery_slice).handle)
    command_bus.register(MarkFileReadyCommand, MarkFileReadyCommandHandler(file_discovery_slice).handle)
    command_bus.register(MarkFileStableCommand, MarkFileStableCommandHandler(file_discovery_slice).handle)
    command_bus.register(UpdateFileGrowthInfoCommand, UpdateFileGrowthInfoCommandHandler(file_discovery_slice).handle)
    command_bus.register(MarkFileGrowingCommand, MarkFileGrowingCommandHandler(file_discovery_slice).handle)
    command_bus.register(MarkFileReadyToStartGrowingCommand, MarkFileReadyToStartGrowingCommandHandler(file_discovery_slice).handle)

    query_bus.register(GetActiveFileByPathQuery, GetActiveFileByPathQueryHandler(file_discovery_slice).handle)
    query_bus.register(ShouldSkipFileProcessingQuery, ShouldSkipFileProcessingQueryHandler(file_discovery_slice).handle)
    query_bus.register(GetCurrentFileForPathQuery, GetCurrentFileForPathQueryHandler(file_discovery_slice).handle)
    query_bus.register(GetFilesByStatusQuery, GetFilesByStatusQueryHandler(file_discovery_slice).handle)
    query_bus.register(GetFilesNeedingGrowthMonitoringQuery, GetFilesNeedingGrowthMonitoringQueryHandler(file_discovery_slice).handle)
