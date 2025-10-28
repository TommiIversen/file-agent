"""
File Discovery Domain Queries
Queries for retrieving file information needed by the file discovery process.
"""
from dataclasses import dataclass

from app.core.cqrs.query import Query
from app.models import FileStatus


@dataclass
class GetActiveFileByPathQuery(Query):
    """Query to get the currently active file for a given path."""
    file_path: str


@dataclass
class ShouldSkipFileProcessingQuery(Query):
    """Query to determine if file processing should be skipped due to cooldown or other rules."""
    file_path: str


@dataclass
class GetCurrentFileForPathQuery(Query):
    """Query to get the current file for a path (including inactive files)."""
    file_path: str


@dataclass
class GetFilesByStatusQuery(Query):
    """Query to get all files with a specific status."""
    status: FileStatus


@dataclass
class GetFilesNeedingGrowthMonitoringQuery(Query):
    """Query to get all files that need growth monitoring."""
    pass