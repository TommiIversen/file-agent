from typing import Dict, Any
import asyncio

from app.core.cqrs.query import QueryHandler
from app.core.file_repository import FileRepository
from app.domains.presentation.queries import GetStatisticsQuery, GetAllFilesQuery, GetRecentFilesQuery, GetStorageStatusQuery
from app.models import FileStatus, TrackedFile, StorageInfoProvider


class GetStatisticsQueryHandler(QueryHandler[GetStatisticsQuery, Dict[str, Any]]):
    def __init__(self, file_repository: FileRepository):
        self.file_repository = file_repository
        self._lock = asyncio.Lock()

    async def handle(self, query: GetStatisticsQuery) -> Dict[str, Any]:
        async with self._lock:
            all_files = await self.file_repository.get_all()
            total_files = len(all_files)
            status_counts: dict[str, int] = {}
            for status in FileStatus:
                status_counts[status.value] = len(
                    [f for f in all_files if f.status == status]
                )
            total_size = sum(f.file_size for f in all_files)
            completed_count = status_counts.get(FileStatus.COMPLETED.value, 0) + status_counts.get(FileStatus.COMPLETED_DELETE_FAILED.value, 0)
            failed_count = status_counts.get(FileStatus.FAILED.value, 0)
            growing_count = sum(
                status_counts.get(s.value, 0)
                for s in [FileStatus.GROWING, FileStatus.READY_TO_START_GROWING, FileStatus.GROWING_COPY]
            )
            active_count = total_files - completed_count - failed_count

            return {
                "total_files": total_files,
                "status_counts": status_counts,
                "total_size_bytes": total_size,
                "totalFiles": total_files,
                "activeFiles": active_count,
                "completedFiles": completed_count,
                "failedFiles": failed_count,
                "growingFiles": growing_count,
            }


class GetAllFilesQueryHandler(QueryHandler[GetAllFilesQuery, list[TrackedFile]]):
    def __init__(self, file_repository: FileRepository):
        self.file_repository = file_repository

    async def handle(self, query: GetAllFilesQuery) -> list[TrackedFile]:
        return await self.file_repository.get_all()


class GetRecentFilesQueryHandler(QueryHandler[GetRecentFilesQuery, list[TrackedFile]]):
    def __init__(self, file_repository: FileRepository):
        self.file_repository = file_repository

    async def handle(self, query: GetRecentFilesQuery) -> list[TrackedFile]:
        return await self.file_repository.get_recent(
            limit=query.limit, offset=query.offset, status=query.status
        )


class GetStorageStatusQueryHandler(QueryHandler[GetStorageStatusQuery, Dict[str, Any]]):
    def __init__(self, storage_monitor: StorageInfoProvider):
        self._storage_monitor = storage_monitor

    async def handle(self, query: GetStorageStatusQuery) -> Dict[str, Any]:
        source_info = self._storage_monitor.get_source_info()
        destination_info = self._storage_monitor.get_destination_info()
        overall_status = self._storage_monitor.get_overall_status()

        # Re-using the serialization logic from the old websocket manager
        def _serialize_storage_info(storage_info) -> dict | None:
            if not storage_info:
                return None
            return {
                "path": storage_info.path,
                "is_accessible": storage_info.is_accessible,
                "has_write_access": storage_info.has_write_access,
                "free_space_gb": round(storage_info.free_space_gb, 2),
                "total_space_gb": round(storage_info.total_space_gb, 2),
                "used_space_gb": round(storage_info.used_space_gb, 2),
                "status": storage_info.status.value,
                "warning_threshold_gb": storage_info.warning_threshold_gb,
                "critical_threshold_gb": storage_info.critical_threshold_gb,
                "last_checked": storage_info.last_checked.isoformat(),
                "error_message": storage_info.error_message,
            }

        return {
            "source": _serialize_storage_info(source_info),
            "destination": _serialize_storage_info(destination_info),
            "overall_status": overall_status.value,
            "monitoring_active": self._storage_monitor.get_monitoring_status()[
                "is_running"
            ],
        }
