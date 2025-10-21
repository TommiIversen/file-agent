import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, List

from app.config import Settings
from app.models import FileStatus, TrackedFile
from app.services.consumer.job_models import QueueJob, JobResult
from app.services.state_manager import StateManager


class JobQueueService:

    def __init__(self, settings: Settings, state_manager: StateManager, storage_monitor=None):
        self.settings = settings
        self.state_manager = state_manager
        self.storage_monitor = storage_monitor  # Add storage monitor reference
        self.job_queue: Optional[asyncio.Queue[QueueJob]] = None

        self._total_jobs_added = 0
        self._total_jobs_processed = 0
        self._failed_jobs: List[JobResult] = []

        self._running = False
        self._producer_task: Optional[asyncio.Task] = None

        logging.info("JobQueueService initialiseret")
        logging.info("Queue vil blive oprettet når start_producer kaldes")

    async def start_producer(self) -> None:
        if self._running:
            logging.warning("Producer task er allerede startet")
            return

        if self.job_queue is None:
            self.job_queue = asyncio.Queue[QueueJob]()
            logging.info("Typed Queue oprettet med kapacitet: unlimited")

        self._running = True

        self.state_manager.subscribe(self._handle_state_change)

        logging.info("Job Queue Producer startet")

        try:
            while self._running:
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            logging.info("Job Queue Producer blev cancelled")
            raise
        except Exception as e:
            logging.error(f"Fejl i producer task: {e}")
            raise
        finally:
            self._running = False
            logging.info("Job Queue Producer stoppet")

    def stop_producer(self) -> None:
        self._running = False
        logging.info("Job Queue Producer stop request")

    async def _handle_state_change(self, update) -> None:
        try:
            if update.new_status in [
                FileStatus.READY,
                FileStatus.READY_TO_START_GROWING,
                # REMOVED GROWING_COPY - causes infinite loop during normal operation
            ]:
                # Check if network is available before queueing
                if await self._is_network_available():
                    await self._add_job_to_queue(update.tracked_file)
                else:
                    # Network is down - keep file as READY but don't queue
                    await self.state_manager.update_file_status_by_id(
                        file_id=update.tracked_file.id,
                        status=FileStatus.WAITING_FOR_NETWORK,
                        error_message="Network unavailable - waiting for recovery",
                    )
                    logging.info(
                        f"⏸️ NETWORK DOWN: {update.tracked_file.file_path} ready but waiting for network"
                    )

        except Exception as e:
            logging.error(f"Fejl ved håndtering af state change: {e}")
    
    async def _is_network_available(self) -> bool:
        """Check if destination network is available"""
        if not self.storage_monitor:
            return True  # Assume available if no storage monitor
            
        try:
            storage_state = self.storage_monitor._storage_state
            dest_info = storage_state.get_destination_info()
            
            if not dest_info:
                return False  # No destination info = not available
                
            # Available if status is OK or WARNING (WARNING still allows copying)
            from app.models import StorageStatus
            return dest_info.status in [StorageStatus.OK, StorageStatus.WARNING]
            
        except Exception as e:
            logging.error(f"Error checking network availability: {e}")
            return True  # Default to available on error
    
    async def process_waiting_network_files(self) -> None:
        """Process all files waiting for network when network becomes available"""
        try:
            waiting_files = await self.state_manager.get_files_by_status(FileStatus.WAITING_FOR_NETWORK)
            
            if not waiting_files:
                logging.info("🌐 NETWORK RECOVERY: No files waiting for network")
                return
                
            logging.info(f"🌐 NETWORK RECOVERY: Processing {len(waiting_files)} files waiting for network")
            
            for tracked_file in waiting_files:
                try:
                    # Transition back to READY so they can be queued normally
                    await self.state_manager.update_file_status_by_id(
                        file_id=tracked_file.id,
                        status=FileStatus.READY,
                        error_message=None,
                    )
                    
                    # They will be picked up by normal _handle_state_change flow
                    logging.info(f"🔄 NETWORK RECOVERY: Reactivated {tracked_file.file_path}")
                    
                except Exception as e:
                    logging.error(f"❌ Error reactivating {tracked_file.file_path}: {e}")
                    
            logging.info(f"✅ NETWORK RECOVERY: Completed processing {len(waiting_files)} files")
            
        except Exception as e:
            logging.error(f"❌ Error processing waiting network files: {e}")

    async def _add_job_to_queue(self, tracked_file: TrackedFile) -> None:
        if self.job_queue is None:
            logging.error("Queue er ikke oprettet endnu!")
            return

        try:
            job = QueueJob(
                tracked_file=tracked_file,
                added_to_queue_at=datetime.now(),
                retry_count=0,
            )

            await self.job_queue.put(job)
            self._total_jobs_added += 1

            await self.state_manager.update_file_status_by_id(
                file_id=job.file_id,
                status=FileStatus.IN_QUEUE,
            )

            logging.info(f"Typed job tilføjet til queue: {job}")
            logging.debug(f"Queue size nu: {self.job_queue.qsize()}")

        except asyncio.QueueFull:
            logging.error(f"Queue er fuld! Kan ikke tilføje: {tracked_file.file_path}")

        except Exception as e:
            logging.error(f"Fejl ved tilføjelse til queue: {e}")

    async def get_next_job(self) -> Optional[QueueJob]:
        if self.job_queue is None:
            return None

        try:
            job = await asyncio.wait_for(self.job_queue.get(), timeout=1.0)
            self._total_jobs_processed += 1

            logging.debug(f"Typed job hentet fra queue: {job}")
            return job

        except asyncio.TimeoutError:
            return None

        except Exception as e:
            logging.error(f"Fejl ved hentning fra queue: {e}")
            return None

    async def mark_job_completed(
            self, job: QueueJob, processing_time: float = 0.0
    ) -> None:
        if self.job_queue is None:
            return

        try:
            self.job_queue.task_done()

            result = JobResult(
                job=job, success=True, processing_time_seconds=processing_time
            )

            logging.info(f"Job completed successfully: {result}")

        except Exception as e:
            logging.error(f"Fejl ved marking job completed: {e}")

    async def mark_job_failed(
            self, job: QueueJob, error_message: str, processing_time: float = 0.0
    ) -> None:
        if self.job_queue is None:
            return

        try:
            self.job_queue.task_done()

            job.mark_retry(error_message)

            result = JobResult(
                job=job,
                success=False,
                processing_time_seconds=processing_time,
                error_message=error_message,
            )

            logging.warning(f"Job failed: {result}")

            self._failed_jobs.append(result)

            if len(self._failed_jobs) > 100:
                self._failed_jobs = self._failed_jobs[-100:]

        except Exception as e:
            logging.error(f"Fejl ved marking job failed: {e}")

    def get_queue_size(self) -> int:
        if self.job_queue is None:
            return 0
        return self.job_queue.qsize()

    def is_queue_empty(self) -> bool:
        if self.job_queue is None:
            return True
        return self.job_queue.empty()

    async def wait_for_queue_empty(self, timeout: Optional[float] = None) -> bool:
        if self.job_queue is None:
            return True

        try:
            await asyncio.wait_for(self.job_queue.join(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def get_queue_statistics(self) -> dict:
        return {
            "is_running": self._running,
            "queue_size": self.get_queue_size(),
            "is_empty": self.is_queue_empty(),
            "total_jobs_added": self._total_jobs_added,
            "total_jobs_processed": self._total_jobs_processed,
            "failed_jobs_count": len(self._failed_jobs),
            "queue_maxsize": self.job_queue.maxsize
            if self.job_queue and self.job_queue.maxsize > 0
            else "unlimited",
        }

    async def get_failed_jobs(self) -> List[JobResult]:
        return self._failed_jobs.copy()

    async def clear_failed_jobs(self) -> int:
        count = len(self._failed_jobs)
        self._failed_jobs.clear()
        logging.info(f"Cleared {count} failed jobs")
        return count

    async def peek_next_job(self) -> Optional[QueueJob]:
        if self.is_queue_empty():
            return None

        return {"queue_size": self.get_queue_size(), "estimated_next_available": True}

    def get_producer_status(self) -> dict:
        return {
            "is_running": self._running,
            "task_created": self._producer_task is not None,
            "subscribed_to_state_manager": True,
        }

    async def handle_destination_unavailable(self) -> None:
        logging.info("⏸️ DESTINATION UNAVAILABLE: Pausing active operations")

        paused_count = await self._pause_active_operations()

        if paused_count > 0:
            logging.info(
                f"⏸️ PAUSED: {paused_count} active operations until destination recovery"
            )
        else:
            logging.info("ℹ️ No active operations to pause")

    async def handle_destination_recovery(self) -> None:
        logging.info("� DESTINATION RECOVERY: Starting intelligent resume process")

        # NOTE: Intelligent resume removed in fail-and-rediscover strategy
        # Paused files concept eliminated - network errors cause immediate FAILED status
        
        logging.info("ℹ️ DESTINATION RECOVERY: No operations needed resume")

    async def _pause_active_operations(self) -> int:
        paused_count = 0

        active_files = await self.state_manager.get_active_copy_files()

        recent_failed_files = await self._get_recent_network_failed_files()

        all_files_to_pause = active_files + recent_failed_files

        for tracked_file in all_files_to_pause:
            current_status = tracked_file.status
            file_path = tracked_file.file_path

            try:
                # NOTE: Pause logic removed in fail-and-rediscover strategy
                # Active operations now fail immediately when destination becomes unavailable
                # Files will be rediscovered by scanner and processed when network returns
                continue

            except Exception as e:
                logging.error(f"❌ Error pausing {file_path}: {e}")

        return paused_count

    async def _resume_paused_file(self, tracked_file: TrackedFile) -> None:
        file_path = tracked_file.file_path
        current_status = tracked_file.status

        try:
            if current_status == FileStatus.PAUSED_IN_QUEUE:
                new_status = FileStatus.IN_QUEUE
            elif current_status == FileStatus.PAUSED_COPYING:
                new_status = FileStatus.READY
            elif current_status == FileStatus.PAUSED_GROWING_COPY:
                # CRITICAL: PAUSED_GROWING_COPY must resume as GROWING_COPY to preserve
                # resume functionality with partial data and existing copy strategy
                new_status = FileStatus.GROWING_COPY
            else:
                logging.warning(
                    f"⚠️ Unknown paused status for {file_path}: {current_status}"
                )
                return

            await self.state_manager.update_file_status_by_id(
                file_id=tracked_file.id,
                status=new_status,
                error_message=None,
                retry_count=0,
            )

            # CRITICAL: For PAUSED_GROWING_COPY -> GROWING_COPY, we need to restart 
            # the growing copy process but with resume capability
            if current_status == FileStatus.PAUSED_GROWING_COPY and new_status == FileStatus.GROWING_COPY:
                # Get the updated tracked file after status change
                updated_file = await self.state_manager.get_file_by_id(tracked_file.id)
                if updated_file:
                    await self._add_job_to_queue(updated_file)
                    logging.info(
                        f"🔄 GROWING COPY RESTART: Added resume job for {file_path} "
                        f"[UUID: {tracked_file.id[:8]}...] - will continue from {tracked_file.bytes_copied:,} bytes"
                    )

            logging.info(
                f"▶️ RESUMED: {file_path} ({current_status} → {new_status}) "
                f"- preserved {tracked_file.bytes_copied:,} bytes"
            )

        except Exception as e:
            logging.error(f"❌ Error resuming {file_path}: {e}")

    # NOTE: _resume_paused_file method removed above in fail-and-rediscover strategy
    # Network errors now cause immediate FAILED status instead of pause/resume

    async def _get_recent_network_failed_files(self) -> List[TrackedFile]:
        cutoff_time = datetime.now() - timedelta(minutes=5)

        recent_failed = []
        all_files = await self.state_manager.get_all_files()

        for tracked_file in all_files:
            if (
                    tracked_file.status == FileStatus.FAILED
                    and tracked_file.last_error_at
                    and tracked_file.last_error_at >= cutoff_time
                    and self._is_likely_network_failure(tracked_file)
            ):
                recent_failed.append(tracked_file)

        if recent_failed:
            logging.info(
                f"🔍 Found {len(recent_failed)} recent network-failed files to pause"
            )

        return recent_failed

    def _is_likely_network_failure(self, tracked_file: TrackedFile) -> bool:
        error_msg = (tracked_file.error_message or "").lower()

        network_indicators = [
            "input/output error",
            "errno 5",
            "paused:",  # Our new pause-classified errors
            "network error",
            "destination unavailable",
            "connection refused",
            "connection timed out",
            "broken pipe",
            "smb error",
            "mount_smbfs",
            "network mount",
        ]

        for indicator in network_indicators:
            if indicator in error_msg:
                return True

        return False
