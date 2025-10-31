import asyncio
import logging
from datetime import datetime
from typing import Optional, List

from app.config import Settings
from app.core.events.event_bus import DomainEventBus
from app.core.events.file_events import FileReadyEvent, FileStatusChangedEvent
from app.models import FileStatus, TrackedFile
from app.services.consumer.job_models import QueueJob, JobResult
from app.core.file_repository import FileRepository
from app.services.copy.growing_copy import GrowingFileCopyStrategy


class JobQueueService:
    def __init__(
        self,
        settings: Settings,
        file_repository: FileRepository,
        event_bus: Optional[DomainEventBus] = None,
        storage_monitor=None,
        copy_strategy=None,
    ):
        self.settings = settings
        self.file_repository = file_repository
        self.storage_monitor = storage_monitor
        self._event_bus = event_bus
        self.copy_strategy = copy_strategy
        self.job_queue: Optional[asyncio.PriorityQueue[QueueJob]] = None

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
            self.job_queue = asyncio.PriorityQueue[QueueJob]()
            logging.info("Typed Queue oprettet med kapacitet: unlimited")

        self._running = True

        if self._event_bus:
            asyncio.create_task(
                self._event_bus.subscribe(FileReadyEvent, self.handle_file_ready)
            )
            logging.info("Subscribed to FileReadyEvent on the event bus")
        else:
            # This should not happen in normal operation with DI, but it's a safeguard.
            logging.error(
                "DomainEventBus not injected, JobQueueService will not be able to queue new files!"
            )

        logging.info("Job Queue Producer startet")

        try:
            while self._running:
                await asyncio.sleep(0.1)

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

    async def handle_file_ready(self, event: FileReadyEvent) -> None:
        """Handles the FileReadyEvent from the event bus."""
        try:
            # Use event.file_id and event.file_path directly
            tracked_file = await self.file_repository.get_by_id(event.file_id)
            if not tracked_file:
                logging.warning(
                    f"Received FileReadyEvent for unknown file ID: {event.file_id}"
                )
                return

            # Guard against re-queuing files that are already being processed.
            # Accept both READY and READY_TO_START_GROWING status
            if tracked_file.status not in [FileStatus.READY, FileStatus.READY_TO_START_GROWING]:
                logging.warning(
                    f"Ignoring FileReadyEvent for {event.file_path} because its status is "
                    f"'{tracked_file.status.value}' instead of READY or READY_TO_START_GROWING."
                )
                return

            if await self._is_network_available():
                await self._add_job_to_queue(tracked_file)
            else:
                tracked_file.status = FileStatus.WAITING_FOR_NETWORK
                tracked_file.error_message = "Network unavailable - waiting for recovery"
                await self.file_repository.update(tracked_file)
                await self._event_bus.publish(
                    FileStatusChangedEvent(
                        file_id=event.file_id,
                        file_path=event.file_path,
                        old_status=FileStatus.READY,
                        new_status=FileStatus.WAITING_FOR_NETWORK,
                        timestamp=datetime.now()
                    )
                )
                logging.info(
                    f"⏸️ NETWORK DOWN: {event.file_path} ready but waiting for network"
                )
        except Exception as e:
            logging.error(f"Error handling FileReadyEvent: {e}")

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
            # Use file_repository to get files by status
            all_files = await self.file_repository.get_all()
            waiting_files = [f for f in all_files if f.status == FileStatus.WAITING_FOR_NETWORK]

            if not waiting_files:
                logging.info("🌐 NETWORK RECOVERY: No files waiting for network")
                return

            logging.info(
                f"🌐 NETWORK RECOVERY: Processing {len(waiting_files)} files waiting for network"
            )

            for tracked_file in waiting_files:
                try:
                    old_status = tracked_file.status
                    tracked_file.status = FileStatus.DISCOVERED
                    tracked_file.error_message = None
                    await self.file_repository.update(tracked_file)
                    await self._event_bus.publish(
                        FileStatusChangedEvent(
                            file_id=tracked_file.id,
                            file_path=tracked_file.file_path,
                            old_status=old_status,
                            new_status=FileStatus.DISCOVERED,
                            timestamp=datetime.now()
                        )
                    )
                    # They will be re-evaluated through normal scanner discovery flow
                    logging.info(
                        f"🔄 NETWORK RECOVERY: Reactivated {tracked_file.file_path} for re-evaluation"
                    )

                except Exception as e:
                    logging.error(
                        f"❌ Error reactivating {tracked_file.file_path}: {e}"
                    )

            logging.info(
                f"✅ NETWORK RECOVERY: Completed processing {len(waiting_files)} files"
            )

        except Exception as e:
            logging.error(f"❌ Error processing waiting network files: {e}")

    async def _add_job_to_queue(self, tracked_file: TrackedFile) -> None:
        if self.job_queue is None:
            logging.error("Queue er ikke oprettet endnu!")
            return

        try:
            is_growing_at_queue_time = False
            if tracked_file.status == FileStatus.READY_TO_START_GROWING:
                is_growing_at_queue_time = True
            elif self.copy_strategy:
                is_growing_at_queue_time = self.copy_strategy._is_file_currently_growing(tracked_file)

            job = QueueJob(
                file_id=tracked_file.id,
                file_path=tracked_file.file_path,
                file_size=tracked_file.file_size,
                creation_time=tracked_file.creation_time,
                is_growing_at_queue_time=is_growing_at_queue_time,
                added_to_queue_at=datetime.now(),
                retry_count=0,
            )

            await self.job_queue.put(job)
            self._total_jobs_added += 1

            old_status = tracked_file.status
            tracked_file.status = FileStatus.IN_QUEUE
            await self.file_repository.update(tracked_file)
            await self._event_bus.publish(
                FileStatusChangedEvent(
                    file_id=job.file_id,
                    file_path=tracked_file.file_path,
                    old_status=old_status,
                    new_status=FileStatus.IN_QUEUE,
                    timestamp=datetime.now()
                )
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
