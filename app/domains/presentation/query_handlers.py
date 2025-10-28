from typing import Dict, Any
import asyncio

from app.core.cqrs.query import QueryHandler
from app.core.file_repository import FileRepository
from app.domains.presentation.queries import GetStatisticsQuery, GetAllFilesQuery, GetStorageStatusQuery
from app.models import FileStatus, TrackedFile
from app.services.storage_monitor import StorageMonitorService


class GetStatisticsQueryHandler(QueryHandler[GetStatisticsQuery, Dict[str, Any]]):
    def __init__(self, file_repository: FileRepository):
        self.file_repository = file_repository
        self._lock = asyncio.Lock()

    def _is_more_current(self, file1: TrackedFile, file2: TrackedFile) -> bool:
        active_statuses = {
            FileStatus.COPYING: 1,
            FileStatus.IN_QUEUE: 2,
            FileStatus.GROWING_COPY: 3,
            FileStatus.READY_TO_START_GROWING: 4,
            FileStatus.READY: 5,
            FileStatus.GROWING: 6,
            FileStatus.DISCOVERED: 7,
            FileStatus.WAITING_FOR_SPACE: 8,
            FileStatus.WAITING_FOR_NETWORK: 8,
            FileStatus.COMPLETED: 9,
            FileStatus.FAILED: 10,
            FileStatus.REMOVED: 11,
            FileStatus.SPACE_ERROR: 12,
        }
        priority1 = active_statuses.get(file1.status, 99)
        priority2 = active_statuses.get(file2.status, 99)
        if priority1 != priority2:
            return priority1 < priority2
        time1 = file1.discovered_at.timestamp() if file1.discovered_at else 0
        time2 = file2.discovered_at.timestamp() if file2.discovered_at else 0
        return time1 > time2

    async def handle(self, query: GetStatisticsQuery) -> Dict[str, Any]:
        async with self._lock:
            current_files = {}
            all_files = await self.file_repository.get_all()
            for tracked_file in all_files:
                current = current_files.get(tracked_file.file_path)
                if not current or self._is_more_current(tracked_file, current):
                    current_files[tracked_file.file_path] = tracked_file
            current_files_list = list(current_files.values())
            total_files = len(current_files_list)
            status_counts = {}
            for status in FileStatus:
                status_counts[status.value] = len(
                    [f for f in current_files_list if f.status == status]
                )
            total_size = sum(f.file_size for f in current_files_list)
            copying_files = [
                f for f in current_files_list if f.status == FileStatus.COPYING
            ]
            growing_files = [
                f
                for f in current_files_list
                if f.status
                in [
                    FileStatus.GROWING,
                    FileStatus.READY_TO_START_GROWING,
                    FileStatus.GROWING_COPY,
                ]
            ]
            return {
                "total_files": total_files,
                "status_counts": status_counts,
                "total_size_bytes": total_size,
                "active_copies": len(copying_files),
                "growing_files": len(growing_files),
            }


class GetAllFilesQueryHandler(QueryHandler[GetAllFilesQuery, list[TrackedFile]]):
    def __init__(self, file_repository: FileRepository):
        self.file_repository = file_repository

    async def handle(self, query: GetAllFilesQuery) -> list[TrackedFile]:
        return await self.file_repository.get_all()


class GetStorageStatusQueryHandler(QueryHandler[GetStorageStatusQuery, Dict[str, Any]]):
    def __init__(self, storage_monitor: StorageMonitorService):
        self._storage_monitor = storage_monitor

    async def handle(self, query: GetStorageStatusQuery) -> Dict[str, Any]:
        source_info = self._storage_monitor.get_source_info()
        destination_info = self._storage_monitor.get_destination_info()
        overall_status = self._storage_monitor.get_overall_status()

        # Re-using the serialization logic from the old websocket manager
        def _serialize_storage_info(storage_info) -> dict:
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
