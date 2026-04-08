"""
File Discovery Query Handlers
Handles queries related to file discovery operations.
"""
from app.core.cqrs.query import QueryHandler
from app.domains.file_discovery.queries import (
    GetActiveFileByPathQuery, 
    ShouldSkipFileProcessingQuery, 
    GetCurrentFileForPathQuery,
    GetFilesByStatusQuery,
    GetFilesNeedingGrowthMonitoringQuery
)
from app.domains.file_discovery.file_discovery_slice import FileDiscoverySlice
from app.models import TrackedFile


class GetActiveFileByPathQueryHandler(QueryHandler[GetActiveFileByPathQuery, TrackedFile | None]):
    """Handles queries for getting the active file for a given path."""

    def __init__(self, file_discovery_slice: FileDiscoverySlice):
        self._file_discovery_slice = file_discovery_slice

    async def handle(self, query: GetActiveFileByPathQuery) -> TrackedFile | None:
        """Get the currently active file for the specified path."""
        return await self._file_discovery_slice.get_active_file_by_path(query.file_path)


class ShouldSkipFileProcessingQueryHandler(QueryHandler[ShouldSkipFileProcessingQuery, bool]):
    """Handles queries for determining if file processing should be skipped."""

    def __init__(self, file_discovery_slice: FileDiscoverySlice):
        self._file_discovery_slice = file_discovery_slice

    async def handle(self, query: ShouldSkipFileProcessingQuery) -> bool:
        """Determine if processing should be skipped for the specified file."""
        return await self._file_discovery_slice.should_skip_file_processing(query.file_path)


class GetCurrentFileForPathQueryHandler(QueryHandler[GetCurrentFileForPathQuery, TrackedFile | None]):
    """Handles queries for getting the current file for a given path."""

    def __init__(self, file_discovery_slice: FileDiscoverySlice):
        self._file_discovery_slice = file_discovery_slice

    async def handle(self, query: GetCurrentFileForPathQuery) -> TrackedFile | None:
        """Get the current file for the specified path."""
        return await self._file_discovery_slice.get_current_file_for_path(query.file_path)


class GetFilesByStatusQueryHandler(QueryHandler[GetFilesByStatusQuery, list[TrackedFile]]):
    """Handles queries for getting files by status."""

    def __init__(self, file_discovery_slice: FileDiscoverySlice):
        self._file_discovery_slice = file_discovery_slice

    async def handle(self, query: GetFilesByStatusQuery) -> list[TrackedFile]:
        """Get all files with the specified status."""
        return await self._file_discovery_slice.get_files_by_status(query.status)


class GetFilesNeedingGrowthMonitoringQueryHandler(QueryHandler[GetFilesNeedingGrowthMonitoringQuery, list[TrackedFile]]):
    """Handles queries for getting files that need growth monitoring."""

    def __init__(self, file_discovery_slice: FileDiscoverySlice):
        self._file_discovery_slice = file_discovery_slice

    async def handle(self, query: GetFilesNeedingGrowthMonitoringQuery) -> list[TrackedFile]:
        """Get all files that need growth monitoring."""
        return await self._file_discovery_slice.get_files_needing_growth_monitoring()