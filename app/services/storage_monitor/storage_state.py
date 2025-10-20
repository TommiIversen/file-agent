from typing import Optional

from ...models import StorageInfo, StorageStatus


class StorageState:

    def __init__(self):
        self._source_info: Optional[StorageInfo] = None
        self._destination_info: Optional[StorageInfo] = None

    def update_source_info(self, info: StorageInfo) -> bool:
        old_status = self._source_info.status if self._source_info else None
        self._source_info = info
        return old_status != info.status

    def update_destination_info(self, info: StorageInfo) -> bool:
        old_status = self._destination_info.status if self._destination_info else None
        self._destination_info = info
        return old_status != info.status

    def get_source_info(self) -> Optional[StorageInfo]:
        return self._source_info

    def get_destination_info(self) -> Optional[StorageInfo]:
        return self._destination_info

    def get_overall_status(self) -> StorageStatus:
        statuses = set()

        if self._source_info:
            statuses.add(self._source_info.status)

        if self._destination_info:
            statuses.add(self._destination_info.status)

        priority_order = [
            StorageStatus.CRITICAL,
            StorageStatus.ERROR,
            StorageStatus.WARNING,
            StorageStatus.OK,
        ]

        for status in priority_order:
            if status in statuses:
                return status

        return StorageStatus.OK

    def get_directory_readiness(self) -> dict:
        return {
            "source_ready": self._source_info.is_accessible
            if self._source_info
            else False,
            "destination_ready": self._destination_info.is_accessible
            if self._destination_info
            else False,
            "source_writable": (
                self._source_info.has_write_access if self._source_info else False
            ),
            "destination_writable": (
                self._destination_info.has_write_access
                if self._destination_info
                else False
            ),
            "last_source_check": self._source_info.last_checked
            if self._source_info
            else None,
            "last_destination_check": self._destination_info.last_checked
            if self._destination_info
            else None,
            "overall_ready": (
                    (self._source_info.is_accessible if self._source_info else False)
                    and (
                        self._destination_info.is_accessible
                        if self._destination_info
                        else False
                    )
            ),
        }

    def get_monitoring_status(self) -> dict:
        return {
            "source_monitored": self._source_info is not None,
            "destination_monitored": self._destination_info is not None,
            "overall_status": self.get_overall_status().value,
        }
