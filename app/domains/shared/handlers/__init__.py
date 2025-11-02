"""Shared domain handlers."""
# Import new handlers from separate files
from .log_query_handlers import LogFileQueryHandler
from .storage_query_handlers import StorageQueryHandler

__all__ = [
    "LogFileQueryHandler",
    "StorageQueryHandler"
]