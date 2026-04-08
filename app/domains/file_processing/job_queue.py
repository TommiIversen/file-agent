import asyncio
import logging
from typing import Optional, List

from app.config import Settings
from app.core.file_state_machine import FileStateMachine
from app.core.exceptions import InvalidTransitionError
from app.models import FileStatus
from app.domains.file_processing.consumer.job_models import QueueJob, JobResult
from app.core.file_repository import FileRepository
from app.domains.file_processing.retry_logic import determine_recovery_status


class JobQueueService:
    def __init__(
        self,
        settings: Settings,
        file_repository: FileRepository,
        state_machine: FileStateMachine,
    ):
        self.settings = settings
        self.file_repository = file_repository
        self._state_machine = state_machine
        self.job_queue: Optional[asyncio.PriorityQueue[QueueJob]] = None

        self._total_jobs_added = 0
        self._total_jobs_processed = 0
        self._failed_jobs: List[JobResult] = []
        self._queue_get_timeout: float = 1.0

        logging.info("JobQueueService initialiseret")

    def initialize_queue(self) -> None:
        """Create the underlying priority queue. Idempotent."""
        if self.job_queue is None:
            self.job_queue = asyncio.PriorityQueue[QueueJob]()
            logging.info("Job queue created (unlimited capacity)")

    async def process_waiting_network_files(self) -> None:
        """Process all files waiting for network when network becomes available."""
        try:
            all_files = await self.file_repository.get_all()
            waiting_files = [f for f in all_files if f.status == FileStatus.WAITING_FOR_NETWORK]

            if not waiting_files:
                logging.info("Network recovery: no files waiting for network")
                return

            logging.info(
                f"Network recovery: processing {len(waiting_files)} files waiting for network"
            )

            for tracked_file in waiting_files:
                try:
                    new_status, reason = determine_recovery_status(tracked_file)
                    logging.info(
                        f"Network recovery: {tracked_file.file_path} -> {new_status.value} ({reason})"
                    )
                    
                    await self._state_machine.transition(
                        file_id=tracked_file.id,
                        new_status=new_status,
                        error_message=None
                    )
                    
                except (InvalidTransitionError, ValueError) as e:
                    logging.warning(f"Could not reactivate file {tracked_file.id}: {e}")
                except Exception as e:
                    logging.error(
                        f"Error reactivating {tracked_file.file_path}: {e}"
                    )

            logging.info(
                f"Network recovery: completed processing {len(waiting_files)} files"
            )

        except Exception as e:
            logging.error(f"Error processing waiting network files: {e}", exc_info=True)

    async def handle_destination_unavailable(self) -> None:
        """Handle destination becoming unavailable — move IN_QUEUE files to WAITING_FOR_NETWORK."""
        try:
            logging.info("Destination unavailable: network disruption detected")
            
            # Drain the physical queue to prevent workers from picking up stale jobs
            drained = self._drain_queue()
            if drained:
                logging.info(f"Drained {drained} jobs from physical queue")

            all_files = await self.file_repository.get_all()
            in_queue_files = [f for f in all_files if f.status == FileStatus.IN_QUEUE]

            if not in_queue_files:
                logging.info("Destination unavailable: no IN_QUEUE files to pause")
                return

            logging.info(
                f"Destination unavailable: pausing {len(in_queue_files)} IN_QUEUE files"
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
                        f"Error pausing {tracked_file.file_path}: {e}"
                    )

            logging.info(
                f"Destination unavailable: paused {paused_count}/{len(in_queue_files)} files"
            )
            
        except Exception as e:
            logging.error(f"Error handling destination unavailable: {e}", exc_info=True)

    def _drain_queue(self) -> int:
        """Drain all pending jobs from the physical queue. Returns count of drained jobs."""
        if self.job_queue is None:
            return 0
        count = 0
        while not self.job_queue.empty():
            try:
                self.job_queue.get_nowait()
                self.job_queue.task_done()
                count += 1
            except asyncio.QueueEmpty:
                break
        return count

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

            logging.debug(f"Job retrieved from queue: {job}")
            return job

        except asyncio.TimeoutError:
            return None

        except Exception as e:
            logging.error(f"Error getting job from queue: {e}", exc_info=True)
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
