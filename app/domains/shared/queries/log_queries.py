"""
Log file management queries for the shared domain.
These queries handle read-only operations for system log files.
"""
from dataclasses import dataclass


@dataclass
class ListLogFilesQuery:
    """Query to list available log files."""
    pass


@dataclass  
class GetLogContentQuery:
    """Query to get the full content of a log file."""
    filename: str


@dataclass
class GetLogContentChunkQuery:
    """Query to get a chunk of log file content with pagination."""
    filename: str
    start: int = 0
    limit: int = 1000


@dataclass
class DownloadLogFileQuery:
    """Query to prepare a log file for download."""
    filename: str