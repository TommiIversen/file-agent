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
from app.domains.file_processing.retry_logic import NetworkRecoveryDecision


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
        self._queue_get_timeout: float = 1.0

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
            logging.error(f"Fejl i producer task: {e}", exc_info=True)
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
                logging.info(" NETWORK RECOVERY: No files waiting for network")
                return

            logging.info(
                f" NETWORK RECOVERY: Processing {len(waiting_files)} files waiting for network"
            )

            for tracked_file in waiting_files:
                try:
                    new_status, reason = NetworkRecoveryDecision.determine_recovery_status(tracked_file)
                    logging.info(
                        f" NETWORK RECOVERY: {tracked_file.file_path} -> {new_status.value} ({reason})"
                    )
                    
                    await self._state_machine.transition(
                        file_id=tracked_file.id,
                        new_status=new_status,
                        error_message=None
                    )
                    
                except (InvalidTransitionError, ValueError) as e:
                    logging.warning(f"Kunne ikke re-aktivere fil {tracked_file.id}: {e}")
                except Exception as e:
                    logging.error(
                        f" Error reactivating {tracked_file.file_path}: {e}"
                    )

            logging.info(
                f" NETWORK RECOVERY: Completed processing {len(waiting_files)} files"
            )

        except Exception as e:
            logging.error(f" Error processing waiting network files: {e}", exc_info=True)

    async def handle_destination_unavailable(self) -> None:
        """Handle destination becoming unavailable — move IN_QUEUE files to WAITING_FOR_NETWORK."""
        try:
            logging.info(" DESTINATION UNAVAILABLE: Network disruption detected")
            
            all_files = await self.file_repository.get_all()
            in_queue_files = [f for f in all_files if f.status == FileStatus.IN_QUEUE]

            if not in_queue_files:
                logging.info(" DESTINATION UNAVAILABLE: No IN_QUEUE files to pause")
                return

            logging.info(
                f" DESTINATION UNAVAILABLE: Pausing {len(in_queue_files)} IN_QUEUE files"
            )

            paused_count = 0
            for tracked_file in in_queue_files:
                try:
                    await self._state_machine.transition(
                        file_id=tracked_file.id,
                        new_status=FileStatus.WAITING_FOR_NETWORK,
                        error_message="Network unavailable - waiting for recovery",
                    )
                    paused_count += 1
                except (InvalidTransitionError, ValueError) as e:
                    logging.warning(
                        f"Could not pause IN_QUEUE file {tracked_file.id}: {e}"
                    )
                except Exception as e:
                    logging.error(
                        f" Error pausing {tracked_file.file_path}: {e}"
                    )

            logging.info(
                f" DESTINATION UNAVAILABLE: Paused {paused_count}/{len(in_queue_files)} files"
            )
            
        except Exception as e:
            logging.error(f" Error handling destination unavailable: {e}", exc_info=True)

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
            job = await asyncio.wait_for(self.job_queue.get(), timeout=self._queue_get_timeout)
            self._total_jobs_processed += 1

            logging.debug(f"Typed job hentet fra queue: {job}")
            return job

        except asyncio.TimeoutError:
            return None

        except Exception as e:
            logging.error(f"Fejl ved hentning fra queue: {e}", exc_info=True)
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
            logging.error(f"Fejl ved marking job completed: {e}", exc_info=True)

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
            logging.error(f"Fejl ved marking job failed: {e}", exc_info=True)
