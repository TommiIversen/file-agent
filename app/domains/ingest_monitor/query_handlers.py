"""
Ingest Monitor Query Handlers
"""
from typing import Any, Dict, Optional
from app.core.cqrs.query import QueryHandler
from app.core.cqrs.shared_queries import GetCurrentFilenameQuery, GetIngestConnectionStatusQuery, GetRecordingSessionTimeQuery
from .queries import GetIngestStatusQuery
from .api_client import IngestApiClient
from .session_tracker import RecordingSessionTracker


class GetIngestStatusQueryHandler(QueryHandler[GetIngestStatusQuery, Dict[str, Any]]):
    """Handler for GetIngestStatusQuery that retrieves cached channel status data."""

    def __init__(self, ingest_monitor_worker):
        self._worker = ingest_monitor_worker

    async def handle(self, query: GetIngestStatusQuery) -> Dict[str, Any]:
        return self._worker.get_status_cache()


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


class GetRecordingSessionTimeQueryHandler(QueryHandler[GetRecordingSessionTimeQuery, Optional[str]]):
    """Handler that returns the canonical session_time for the current/recent recording."""

    def __init__(self, session_tracker: RecordingSessionTracker) -> None:
        self._session_tracker = session_tracker

    async def handle(self, query: GetRecordingSessionTimeQuery) -> Optional[str]:
        return self._session_tracker.get_session_time(query.file_creation_time)
