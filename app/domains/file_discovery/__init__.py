"""
File Discovery Domain
Contains all components related to file discovery operations.
"""
from .file_discovery_slice import FileDiscoverySlice
from .commands import AddFileCommand, MarkFileReadyCommand, MarkFileStableCommand
from .queries import GetActiveFileByPathQuery, ShouldSkipFileProcessingQuery, GetCurrentFileForPathQuery
from .command_handlers import AddFileCommandHandler, MarkFileReadyCommandHandler, MarkFileStableCommandHandler
from .query_handlers import GetActiveFileByPathQueryHandler, ShouldSkipFileProcessingQueryHandler, GetCurrentFileForPathQueryHandler
from .domain_objects import ScanConfiguration

__all__ = [
    "FileDiscoverySlice",
    "AddFileCommand",
    "MarkFileReadyCommand", 
    "MarkFileStableCommand",
    "GetActiveFileByPathQuery",
    "ShouldSkipFileProcessingQuery",
    "GetCurrentFileForPathQuery",
    "AddFileCommandHandler",
    "MarkFileReadyCommandHandler",
    "MarkFileStableCommandHandler", 
    "GetActiveFileByPathQueryHandler",
    "ShouldSkipFileProcessingQueryHandler",
    "GetCurrentFileForPathQueryHandler",
    "ScanConfiguration",
]