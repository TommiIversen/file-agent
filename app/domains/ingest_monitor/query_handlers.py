"""
Ingest Monitor Query Handlers
"""
from typing import Any, Dict, Optional
from app.core.cqrs.query import QueryHandler
from app.core.cqrs.shared_queries import GetCurrentFilenameQuery, GetIngestConnectionStatusQuery
from .queries import GetIngestStatusQuery, GetRecordingPathsQuery
from .api_client import IngestApiClient


class GetIngestStatusQueryHandler(QueryHandler[GetIngestStatusQuery, Dict[str, Any]]):
    """Handler for GetIngestStatusQuery that retrieves cached channel status data."""

    def __init__(self, ingest_monitor_worker):
        self._worker = ingest_monitor_worker

    async def handle(self, query: GetIngestStatusQuery) -> Dict[str, Any]:
        return self._worker.get_status_cache()


class GetRecordingPathsQueryHandler(QueryHandler[GetRecordingPathsQuery, Dict[str, Any]]):
    """Handler for GetRecordingPathsQuery - returns cached recording paths."""

    def __init__(self, ingest_monitor_worker):
        self._worker = ingest_monitor_worker

    async def handle(self, query: GetRecordingPathsQuery) -> Dict[str, Any]:
        return self._worker.get_recording_paths()


class GetIngestConnectionStatusQueryHandler(QueryHandler[GetIngestConnectionStatusQuery, Dict[str, Any]]):
    """Handler for GetIngestConnectionStatusQuery - returns connection status."""

    def __init__(self, ingest_monitor_worker):
        self._worker = ingest_monitor_worker

    async def handle(self, query: GetIngestConnectionStatusQuery) -> Dict[str, Any]:
        return {"is_connected": self._worker.get_connection_status()}


class GetCurrentFilenameQueryHandler(QueryHandler[GetCurrentFilenameQuery, Optional[str]]):
    """Handler for GetCurrentFilenameQuery — fetches filename prefix from Justin API."""

    def __init__(self, api_client: IngestApiClient) -> None:
        self._api_client = api_client

    async def handle(self, query: GetCurrentFilenameQuery) -> Optional[str]:
        return await self._api_client.get_current_filename(query.channel)
