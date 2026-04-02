"""
Ingest Monitor Query Handlers
"""
from typing import Dict, Any
from app.core.cqrs.query import QueryHandler
from .queries import GetIngestStatusQuery, GetRecordingPathsQuery


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
