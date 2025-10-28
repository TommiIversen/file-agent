import asyncio
import logging
from typing import Optional

from app.core.events.event_bus import DomainEventBus

from .directory_manager import DirectoryManager
from .mount_status_broadcaster import MountStatusBroadcaster
from .notification_handler import NotificationHandler
from .storage_state import StorageState
from ..storage_checker import StorageChecker
from ...config import Settings
from ...models import StorageInfo, StorageStatus


class StorageMonitorService:
    def __init__(
        self,
        settings: Settings,
        storage_checker: StorageChecker,
        event_bus: DomainEventBus,
        network_mount_service=None,
        job_queue=None,
    ):
        self._settings = settings
        self._storage_checker = storage_checker
        self._network_mount_service = network_mount_service
        self._job_queue = job_queue

        self._storage_state = StorageState()
        self._directory_manager = DirectoryManager()
        self._notification_handler = NotificationHandler(event_bus)
        self._mount_broadcaster = MountStatusBroadcaster(self._notification_handler)

        self._is_running = False
        self._monitor_task: Optional[asyncio.Task] = None

        logging.info(
            "StorageMonitorService initialized with SRP-compliant architecture"
        )

    async def start_monitoring(self) -> None:
        if self._is_running:
            logging.warning("Storage monitoring already running")
            return

        self._is_running = True
        self._monitor_task = asyncio.create_task(self._monitoring_loop())
        logging.info("Storage monitoring started")

        await self._check_all_storage()

    async def stop_monitoring(self) -> None:
        if not self._is_running:
            return

        self._is_running = False

        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        logging.info("Storage monitoring stopped")

    async def _monitoring_loop(self) -> None:
        logging.info(
            f"Storage monitoring loop starting - checking every {self._settings.storage_check_interval_seconds}s"
        )
        try:
            while self._is_running:
                try:
                    await self._check_all_storage()
                except Exception as e:
                    logging.error(f"Error in storage monitoring loop: {e}")

                await asyncio.sleep(self._settings.storage_check_interval_seconds)

        except asyncio.CancelledError:
            logging.debug("Storage monitoring loop cancelled")
        except Exception as e:
            logging.error(f"Unexpected error in monitoring loop: {e}")

    async def _check_all_storage(self) -> None:
        await self._check_single_storage(
            storage_type="source",
            path=self._settings.source_directory,
            warning_threshold=self._settings.source_warning_threshold_gb,
            critical_threshold=self._settings.source_critical_threshold_gb,
        )

        await self._check_single_storage(
            storage_type="destination",
            path=self._settings.destination_directory,
            warning_threshold=self._settings.destination_warning_threshold_gb,
            critical_threshold=self._settings.destination_critical_threshold_gb,
        )

    async def _check_single_storage(
        self,
        storage_type: str,
        path: str,
        warning_threshold: float,
        critical_threshold: float,
    ) -> None:
        try:
            new_info = await self._storage_checker.check_path(
                path=path,
                warning_threshold_gb=warning_threshold,
                critical_threshold_gb=critical_threshold,
            )

            if not new_info.is_accessible:
                logging.warning(
                    f"{storage_type.title()} directory not accessible: {path}."
                )

                mount_attempted = False
                if storage_type == "destination" and self._network_mount_service:
                    if self._network_mount_service.is_network_mount_configured():
                        share_url = self._network_mount_service.get_network_share_url()
                        if share_url:
                            logging.info(
                                f"Attempting network mount for destination: {share_url}"
                            )

                            await self._mount_broadcaster.broadcast_mount_attempt(
                                storage_type=storage_type,
                                share_url=share_url,
                                target_path=path,
                            )

                            mount_success = await self._network_mount_service.ensure_mount_available(
                                share_url, path
                            )
                            mount_attempted = True

                            if mount_success:
                                logging.info(
                                    f"Network mount successful, re-checking storage: {path}"
                                )

                                await self._mount_broadcaster.broadcast_mount_success(
                                    storage_type=storage_type,
                                    share_url=share_url,
                                    target_path=path,
                                )

                                new_info = await self._storage_checker.check_path(
                                    path=path,
                                    warning_threshold_gb=warning_threshold,
                                    critical_threshold_gb=critical_threshold,
                                )
                            else:
                                await self._mount_broadcaster.broadcast_mount_failure(
                                    storage_type=storage_type,
                                    share_url=share_url,
                                    target_path=path,
                                )
                    else:
                        await self._mount_broadcaster.broadcast_not_configured(
                            storage_type=storage_type, target_path=path
                        )

                if not new_info.is_accessible and not mount_attempted:
                    logging.info(f"Attempting directory recreation: {path}")
                    recreation_success = (
                        await self._directory_manager.ensure_directory_exists(
                            path, storage_type
                        )
                    )

                    if recreation_success:
                        logging.info(
                            f"Re-checking {storage_type} storage after directory recreation"
                        )
                        new_info = await self._storage_checker.check_path(
                            path=path,
                            warning_threshold_gb=warning_threshold,
                            critical_threshold_gb=critical_threshold,
                        )

            old_info = self._get_current_info(storage_type)
            self._update_storage_info(storage_type, new_info)

            # Log storage status for visibility
            if new_info.is_accessible:
                logging.info(
                    f"Storage check - {storage_type.title()}: "
                    f"{new_info.free_space_gb:.2f}GB free / {new_info.total_space_gb:.2f}GB total "
                    f"({new_info.status.value}) at {path}"
                )
            else:
                logging.warning(
                    f"Storage check - {storage_type.title()}: Not accessible at {path}"
                )

            await self._notification_handler.handle_status_change(
                storage_type, old_info, new_info
            )

            if self._is_destination_unavailable(storage_type, old_info, new_info):
                await self._handle_destination_unavailable(
                    storage_type, old_info, new_info
                )
            elif self._is_destination_recovery(storage_type, old_info, new_info):
                await self._handle_destination_recovery(
                    storage_type, old_info, new_info
                )

        except Exception as e:
            logging.error(f"Error checking {storage_type} storage at {path}: {e}")

    def _get_current_info(self, storage_type: str) -> Optional[StorageInfo]:
        if storage_type == "source":
            return self._storage_state.get_source_info()
        else:
            return self._storage_state.get_destination_info()

    def _update_storage_info(self, storage_type: str, info: StorageInfo) -> None:
        if storage_type == "source":
            self._storage_state.update_source_info(info)
        else:
            self._storage_state.update_destination_info(info)

    async def trigger_immediate_check(self, storage_type: str = "destination") -> None:
        if not self._is_running:
            logging.warning(
                f"Storage monitoring not running - cannot trigger immediate {storage_type} check"
            )
            return

        logging.debug(f"Triggering immediate {storage_type} check")

        if storage_type == "source":
            await self._check_single_storage(
                storage_type="source",
                path=self._settings.source_directory,
                warning_threshold=self._settings.source_warning_threshold_gb,
                critical_threshold=self._settings.source_critical_threshold_gb,
            )
        else:
            await self._check_single_storage(
                storage_type="destination",
                path=self._settings.destination_directory,
                warning_threshold=self._settings.destination_warning_threshold_gb,
                critical_threshold=self._settings.destination_critical_threshold_gb,
            )

    def get_source_info(self) -> Optional[StorageInfo]:
        return self._storage_state.get_source_info()

    def get_destination_info(self) -> Optional[StorageInfo]:
        return self._storage_state.get_destination_info()

    def get_overall_status(self) -> StorageStatus:
        return self._storage_state.get_overall_status()

    def get_directory_readiness(self) -> dict:
        return self._storage_state.get_directory_readiness()

    def get_monitoring_status(self) -> dict:
        status = self._storage_state.get_monitoring_status()
        status.update(
            {
                "is_running": self._is_running,
                "check_interval_seconds": self._settings.storage_check_interval_seconds,
            }
        )
        return status

    def is_destination_available(self) -> bool:
        """Check if destination storage is available and accessible."""
        destination_info = self.get_destination_info()
        return destination_info is not None and destination_info.status == StorageStatus.OK

    def _is_destination_recovery(
        self, storage_type: str, old_info: Optional[StorageInfo], new_info: StorageInfo
    ) -> bool:
        if storage_type != "destination":
            return False

        if not old_info:
            return False

        problematic_states = [StorageStatus.ERROR, StorageStatus.CRITICAL]
        is_recovery = (
            old_info.status in problematic_states
            and new_info.status == StorageStatus.OK
        )

        if is_recovery:
            logging.info(
                f"🔄 DESTINATION RECOVERY DETECTED: {old_info.status} → {new_info.status} "
                f"(path: {new_info.path})"
            )

        return is_recovery

    def _is_destination_unavailable(
        self, storage_type: str, old_info: Optional[StorageInfo], new_info: StorageInfo
    ) -> bool:
        if storage_type != "destination":
            return False

        if not old_info:
            return False

        problematic_states = [StorageStatus.ERROR, StorageStatus.CRITICAL]
        is_unavailable = (
            old_info.status == StorageStatus.OK
            and new_info.status in problematic_states
        )

        if is_unavailable:
            logging.warning(
                f"⏸️ DESTINATION UNAVAILABLE: {old_info.status} → {new_info.status} "
                f"(path: {new_info.path})"
            )

        return is_unavailable

    async def _handle_destination_unavailable(
        self, storage_type: str, old_info: StorageInfo, new_info: StorageInfo
    ) -> None:
        if not self._job_queue:
            logging.warning("⚠️ Job queue not available - cannot pause operations")
            return

        try:
            unavailable_reason = f"{old_info.status} → {new_info.status}"

            logging.warning(
                f"⏸️ PAUSING OPERATIONS: {unavailable_reason} "
                f"(Reason: {new_info.error_message or 'Unknown'})"
            )

            await self._job_queue.handle_destination_unavailable()

            logging.info("⏸️ Operations paused successfully - awaiting recovery")

        except Exception as e:
            logging.error(f"ERROR: Error during destination pause handling: {e}")

    async def _handle_destination_recovery(
        self, storage_type: str, old_info: StorageInfo, new_info: StorageInfo
    ) -> None:
        if not self._job_queue:
            logging.warning(
                "⚠️ Job queue not available - cannot perform automatic recovery"
            )
            return

        try:
            recovery_reason = f"{old_info.status} → {new_info.status}"

            logging.info(
                f"🚀 INITIATING UNIVERSAL RECOVERY: {recovery_reason} "
                f"(Free space: {new_info.free_space_gb:.1f} GB)"
            )

            # Process files waiting for network when destination comes back online
            await self._job_queue.process_waiting_network_files()

            logging.info("✅ Intelligent resume initiated successfully")

        except Exception as e:
            logging.error(f"ERROR: Error during universal recovery: {e}")
