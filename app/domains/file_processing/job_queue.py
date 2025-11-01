import asyncio
import logging
from typing import Optional, List

from app.config import Settings
from app.core.events.event_bus import DomainEventBus
from app.core.file_state_machine import FileStateMachine
from app.core.exceptions import InvalidTransitionError
from app.models import FileStatus
from app.domains.file_processing.consumer.job_models import QueueJob, JobResult
from app.core.file_repository import FileRepository


class JobQueueService:
    def __init__(
        self,
        settings: Settings,
        file_repository: FileRepository,
        event_bus: DomainEventBus,
        state_machine: FileStateMachine,
    ):
        self.settings = settings
        self.file_repository = file_repository
        self._event_bus = event_bus
        self._state_machine = state_machine
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

        # Event subscription is now handled by CQRS registration
        # No longer subscribing directly to FileReadyEvent here
        
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
                    await self._state_machine.transition(
                        file_id=tracked_file.id,
                        new_status=FileStatus.DISCOVERED,
                        error_message=None
                    )
                    logging.info(
                        f"🔄 NETWORK RECOVERY: Reactivated {tracked_file.file_path} for re-evaluation"
                    )
                except (InvalidTransitionError, ValueError) as e:
                    logging.warning(f"Kunne ikke re-aktivere fil {tracked_file.id}: {e}")
                except Exception as e:
                    logging.error(
                        f"❌ Error reactivating {tracked_file.file_path}: {e}"
                    )

            logging.info(
                f"✅ NETWORK RECOVERY: Completed processing {len(waiting_files)} files"
            )

        except Exception as e:
            logging.error(f"❌ Error processing waiting network files: {e}")

    async def handle_destination_unavailable(self) -> None:
        """Handle destination becoming unavailable - similar to previous StateManager version"""
        try:
            logging.info("🔴 DESTINATION UNAVAILABLE: Network disruption detected")
            
            # In the previous version, files would automatically be checked for network availability
            # before queueing in _handle_state_change. Here we don't need to do much since:
            # 1. New files will be caught by _is_network_available() in handle_file_ready()
            # 2. Files in queue will be handled by consumer with retry logic
            # 3. Recovery happens through process_waiting_network_files()
            
            logging.info("⏸️ Destination unavailable handling completed - relying on existing network checks")
            
        except Exception as e:
            logging.error(f"❌ Error handling destination unavailable: {e}")

    def get_queue(self) -> Optional[asyncio.PriorityQueue[QueueJob]]:
        """
        Returns the actual queue for command handlers to use.
        
        This method provides access to the underlying queue for the CQRS
        command handlers to add jobs directly.
        """
        return self.job_queue

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
