"""
Registration and setup for Shared Domain.

This module handles the registration of all CQRS handlers (command handlers,
query handlers) for the shared domain with the command bus and query bus.
"""
from app.core.cqrs.command_bus import CommandBus
from app.core.cqrs.query_bus import QueryBus
from app.dependencies import get_settings
from .commands import ReloadConfigCommand, RestartApplicationCommand
from .queries import GetSettingsQuery, GetConfigInfoQuery
from .queries.log_queries import (
    ListLogFilesQuery, GetLogContentQuery, GetLogContentChunkQuery, DownloadLogFileQuery
)
from .queries.storage_queries import GetSourceStorageQuery, GetDestinationStorageQuery
from .config_handlers import (
    ReloadConfigCommandHandler, RestartApplicationCommandHandler,
    GetSettingsQueryHandler, GetConfigInfoQueryHandler
)
from .handlers.log_query_handlers import LogFileQueryHandler
from .handlers.storage_query_handlers import StorageQueryHandler


def register_shared_domain(command_bus: CommandBus, query_bus: QueryBus):
    """
    Registers all handlers for the Shared domain.
    
    This function sets up the complete CQRS infrastructure for shared functionality:
    - Query handlers for system information
    - Command handlers for system operations
    - Log file management query handlers
    - Storage monitoring query handlers
    - Proper dependency injection for all handlers
    """
    # Get current settings for injection
    settings = get_settings()
    
    # Create handler instances
    log_handler = LogFileQueryHandler()
    storage_handler = StorageQueryHandler()
    
    # Register Query Handlers - System
    query_bus.register(GetSettingsQuery, GetSettingsQueryHandler(settings).handle)
    query_bus.register(GetConfigInfoQuery, GetConfigInfoQueryHandler(settings).handle)
    
    # Register Query Handlers - Log Files
    query_bus.register(ListLogFilesQuery, log_handler.handle_list_log_files)
    query_bus.register(GetLogContentQuery, log_handler.handle_get_log_content)
    query_bus.register(GetLogContentChunkQuery, log_handler.handle_get_log_content_chunk)
    query_bus.register(DownloadLogFileQuery, log_handler.handle_download_log_file)
    
    # Register Query Handlers - Storage
    query_bus.register(GetSourceStorageQuery, storage_handler.handle_get_source_storage)
    query_bus.register(GetDestinationStorageQuery, storage_handler.handle_get_destination_storage)
    
    # Register Command Handlers  
    command_bus.register(ReloadConfigCommand, ReloadConfigCommandHandler().handle)
    command_bus.register(RestartApplicationCommand, RestartApplicationCommandHandler().handle)