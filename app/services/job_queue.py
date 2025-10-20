"""
Job Queue Service for File Transfer Agent.

JobQueueService håndterer producer/consumer pattern mellem:
- Producer: FileScannerService (tilføjer Ready filer til queue)
- Consumer: FileCopyService (henter filer fra queue til kopiering)

Implementerer robust queue management med proper error handling,
metrics tracking og graceful shutdown capabilities.
"""

import asyncio
import logging
from typing import Optional, List
from datetime import datetime

from app.config import Settings
from app.models import FileStatus, TrackedFile
from app.services.state_manager import StateManager
from app.services.consumer.job_models import QueueJob, JobResult


class JobQueueService:
    """
    Job queue service der håndterer producer/consumer pattern.

    Ansvar:
    1. Producer Operations: Tilføj Ready filer til asyncio.Queue
    2. Consumer Support: Provide interface til FileCopyService
    3. Queue Management: Monitoring, statistics, graceful shutdown
    4. Error Handling: Dead letter queue for failed jobs
    """

    def __init__(self, settings: Settings, state_manager: StateManager):
        """
        Initialize JobQueueService.

        Args:
            settings: Application settings
            state_manager: Central state manager
        """
        self.settings = settings
        self.state_manager = state_manager
        self.job_queue: Optional[asyncio.Queue[QueueJob]] = None  # Typed queue

        # Queue statistics
        self._total_jobs_added = 0
        self._total_jobs_processed = 0
        self._failed_jobs: List[JobResult] = []  # Now stores typed results

        # Queue management
        self._running = False
        self._producer_task: Optional[asyncio.Task] = None

        logging.info("JobQueueService initialiseret")
        logging.info("Queue vil blive oprettet når start_producer kaldes")

    async def start_producer(self) -> None:
        """
        Start producer task der lytter på Ready filer og tilføjer til queue.

        Producer task lytter på StateManager events og tilføjer filer
        med status READY til job queue automatisk.
        """
        if self._running:
            logging.warning("Producer task er allerede startet")
            return

        # Create typed queue if not exists
        if self.job_queue is None:
            self.job_queue = asyncio.Queue[QueueJob]()
            logging.info("Typed Queue oprettet med kapacitet: unlimited")

        self._running = True

        # Subscribe til StateManager events
        self.state_manager.subscribe(self._handle_state_change)

        logging.info("Job Queue Producer startet")

        try:
            # Producer kører indefinitely og lytter på events
            while self._running:
                await asyncio.sleep(1)  # Keep alive loop

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
        """Stop producer task gracefully."""
        self._running = False
        logging.info("Job Queue Producer stop request")

    async def _handle_state_change(self, update) -> None:
        """
        Handle StateManager events og tilføj Ready filer til queue.

        Args:
            update: FileStateUpdate event fra StateManager
        """
        try:
            # Interesseret i filer der bliver Ready eller ReadyToStartGrowing
            if update.new_status in [
                FileStatus.READY,
                FileStatus.READY_TO_START_GROWING,
            ]:
                await self._add_job_to_queue(update.tracked_file)

        except Exception as e:
            logging.error(f"Fejl ved håndtering af state change: {e}")

    async def _add_job_to_queue(self, tracked_file: TrackedFile) -> None:
        """
        Tilføj fil job til queue og opdater status til InQueue.

        Args:
            tracked_file: TrackedFile objekt der skal kopieres
        """
        if self.job_queue is None:
            logging.error("Queue er ikke oprettet endnu!")
            return

        try:
            # Opret typed job objekt med TrackedFile reference
            job = QueueJob(
                tracked_file=tracked_file,
                added_to_queue_at=datetime.now(),
                retry_count=0
            )

            # Tilføj til queue (non-blocking)
            await self.job_queue.put(job)
            self._total_jobs_added += 1

            # Opdater fil status til InQueue - UUID precision via job object
            await self.state_manager.update_file_status_by_id(
                file_id=job.file_id,  # UUID from job object
                status=FileStatus.IN_QUEUE
            )

            logging.info(f"Typed job tilføjet til queue: {job}")
            logging.debug(f"Queue size nu: {self.job_queue.qsize()}")

        except asyncio.QueueFull:
            logging.error(f"Queue er fuld! Kan ikke tilføje: {tracked_file.file_path}")
            # Kunne implementere retry logic her

        except Exception as e:
            logging.error(f"Fejl ved tilføjelse til queue: {e}")

    async def get_next_job(self) -> Optional[QueueJob]:
        """
        Hent næste job fra queue (til brug af FileCopyService).

        Returns:
            QueueJob object eller None hvis queue er tom
        """
        if self.job_queue is None:
            return None

        try:
            # Non-blocking get med timeout
            job = await asyncio.wait_for(self.job_queue.get(), timeout=1.0)
            self._total_jobs_processed += 1

            logging.debug(f"Typed job hentet fra queue: {job}")
            return job

        except asyncio.TimeoutError:
            # Queue er tom - ikke en fejl
            return None

        except Exception as e:
            logging.error(f"Fejl ved hentning fra queue: {e}")
            return None

    async def mark_job_completed(self, job: QueueJob, processing_time: float = 0.0) -> None:
        """
        Marker job som completed (kaldt af FileCopyService).

        Args:
            job: QueueJob object der blev completed
            processing_time: Processing time in seconds for metrics
        """
        if self.job_queue is None:
            return

        try:
            # Marker task som done i asyncio.Queue
            self.job_queue.task_done()

            # Create success result for metrics
            result = JobResult(
                job=job,
                success=True,
                processing_time_seconds=processing_time
            )

            logging.info(f"Job completed successfully: {result}")

        except Exception as e:
            logging.error(f"Fejl ved marking job completed: {e}")

    async def mark_job_failed(self, job: QueueJob, error_message: str, processing_time: float = 0.0) -> None:
        """
        Marker job som failed og håndter retry logic.

        Args:
            job: QueueJob object der fejlede
            error_message: Fejlbesked
            processing_time: Processing time before failure
        """
        if self.job_queue is None:
            return

        try:
            # Marker task som done i asyncio.Queue
            self.job_queue.task_done()

            # Mark retry information on job object
            job.mark_retry(error_message)

            # Create failure result for metrics
            result = JobResult(
                job=job,
                success=False,
                processing_time_seconds=processing_time,
                error_message=error_message
            )

            # Log failure with structured information
            logging.warning(f"Job failed: {result}")

            # Tilføj til failed jobs liste for metrics tracking
            self._failed_jobs.append(result)

            # Keep only last 100 failed jobs for memory management
            if len(self._failed_jobs) > 100:
                self._failed_jobs = self._failed_jobs[-100:]

        except Exception as e:
            logging.error(f"Fejl ved marking job failed: {e}")

    async def requeue_job(self, job: QueueJob) -> None:
        """
        Put job tilbage i queue for retry.

        Args:
            job: QueueJob object der skal requeues
        """
        if self.job_queue is None:
            logging.error("Queue er ikke oprettet endnu!")
            return

        try:
            # Mark requeue information on job object
            job.mark_requeued()

            # Put job tilbage i queue
            await self.job_queue.put(job)

            logging.info(f"Job requeued: {job}")

        except Exception as e:
            logging.error(f"Fejl ved requeue af job: {e}")

    def get_queue_size(self) -> int:
        """
        Hent antal jobs i queue.

        Returns:
            Antal jobs der venter i queue
        """
        if self.job_queue is None:
            return 0
        return self.job_queue.qsize()

    def is_queue_empty(self) -> bool:
        """
        Check om queue er tom.

        Returns:
            True hvis queue er tom
        """
        if self.job_queue is None:
            return True
        return self.job_queue.empty()

    async def wait_for_queue_empty(self, timeout: Optional[float] = None) -> bool:
        """
        Vent på at queue bliver tom (alle jobs processed).

        Args:
            timeout: Max tid at vente (None = ingen timeout)

        Returns:
            True hvis queue blev tom, False ved timeout
        """
        if self.job_queue is None:
            return True

        try:
            await asyncio.wait_for(self.job_queue.join(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def get_queue_statistics(self) -> dict:
        """
        Hent detaljerede queue statistikker.

        Returns:
            Dictionary med queue statistikker
        """
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
        """
        Hent liste af failed jobs.

        Returns:
            Liste af failed job dictionaries
        """
        return self._failed_jobs.copy()

    async def clear_failed_jobs(self) -> int:
        """
        Ryd failed jobs liste.

        Returns:
            Antal jobs der blev cleared
        """
        count = len(self._failed_jobs)
        self._failed_jobs.clear()
        logging.info(f"Cleared {count} failed jobs")
        return count

    async def peek_next_job(self) -> Optional[QueueJob]:
        """
        Se næste job i queue uden at fjerne det.

        Returns:
            Næste job dictionary eller None hvis tom
        """
        if self.is_queue_empty():
            return None

        # Dette er en begrænsning af asyncio.Queue - vi kan ikke peek
        # Men vi kan returnere en kopi af job statistikker
        return {"queue_size": self.get_queue_size(), "estimated_next_available": True}

    def get_producer_status(self) -> dict:
        """
        Hent producer task status.

        Returns:
            Dictionary med producer status
        """
        return {
            "is_running": self._running,
            "task_created": self._producer_task is not None,
            "subscribed_to_state_manager": True,  # Vi subscriber i start_producer
        }

    async def handle_destination_unavailable(self) -> None:
        """
        Håndter destination unavailability - pause aktive operations.

        Når destination bliver unavailable, skal vi:
        1. Pause alle aktive copy operations (de får I/O errors)
        2. Pause alle jobs i queue (de kan ikke starte)
        3. Bevare interrupt context for seamless resume
        """
        logging.info("⏸️ DESTINATION UNAVAILABLE: Pausing active operations")

        # Få alle aktive operations der skal pauses
        paused_count = await self._pause_active_operations()

        if paused_count > 0:
            logging.info(
                f"⏸️ PAUSED: {paused_count} active operations until destination recovery"
            )
        else:
            logging.info("ℹ️ No active operations to pause")

    async def handle_destination_recovery(self) -> None:
        """
        Håndter destination recovery - resume paused operations med preserved context.

        Dette er det intelligente recovery system der:
        - Resumer paused operations med preserved bytes offset
        - Bruger existing resumable strategies
        - Fortsætter seamless fra hvor det slap
        """
        logging.info("� DESTINATION RECOVERY: Starting intelligent resume process")

        # Få alle paused operations der kan resumes
        paused_files = await self.state_manager.get_paused_files()

        total_resumed = 0

        # Resume paused files med preserved context
        if paused_files:
            logging.info(f"▶️ Resuming {len(paused_files)} paused operations")
            for tracked_file in paused_files:
                await self._resume_paused_file(tracked_file)
                total_resumed += 1

        if total_resumed > 0:
            logging.info(
                f"✅ DESTINATION RECOVERY COMPLETE: Successfully resumed {total_resumed} operations"
            )
        else:
            logging.info("ℹ️ DESTINATION RECOVERY: No operations needed resume")

    async def _pause_active_operations(self) -> int:
        """
        Pause alle aktive copy operations og jobs i queue.

        Returns:
            Antal operations der blev paused
        """
        paused_count = 0

        # Få alle aktive operations
        active_files = await self.state_manager.get_active_copy_files()

        # ALSO get recent FAILED files that might be network-related
        recent_failed_files = await self._get_recent_network_failed_files()

        # Combine active and recent failed files
        all_files_to_pause = active_files + recent_failed_files

        for tracked_file in all_files_to_pause:
            current_status = tracked_file.status
            file_path = tracked_file.file_path

            try:
                # Map current status to appropriate paused status
                if current_status == FileStatus.IN_QUEUE:
                    new_status = FileStatus.PAUSED_IN_QUEUE
                elif current_status == FileStatus.COPYING:
                    new_status = FileStatus.PAUSED_COPYING
                elif current_status == FileStatus.GROWING_COPY:
                    new_status = FileStatus.PAUSED_GROWING_COPY
                elif (
                    current_status == FileStatus.FAILED
                    and self._is_likely_network_failure(tracked_file)
                ):
                    # Convert network-related FAILED to appropriate pause state
                    if tracked_file.bytes_copied and tracked_file.bytes_copied > 0:
                        # Had progress, likely was copying when it failed
                        new_status = (
                            FileStatus.PAUSED_GROWING_COPY
                            if "growing" in (tracked_file.error_message or "").lower()
                            else FileStatus.PAUSED_COPYING
                        )
                    else:
                        # No progress, likely failed early
                        new_status = FileStatus.PAUSED_IN_QUEUE
                else:
                    continue  # Skip files not in active copy states or non-network failures

                # Pause med preserved context (bytes_copied, copy_progress bevares) - UUID precision
                await self.state_manager.update_file_status_by_id(
                    file_id=tracked_file.id,  # Precise UUID reference
                    status=new_status,
                    error_message="Paused - destination unavailable",
                    # Note: bytes_copied og copy_progress IKKE reset - bevares for resume
                )

                paused_count += 1
                logging.info(f"⏸️ PAUSED: {file_path} ({current_status} → {new_status})")

            except Exception as e:
                logging.error(f"❌ Error pausing {file_path}: {e}")

        return paused_count

    async def _resume_paused_file(self, tracked_file: TrackedFile) -> None:
        """
        Resume en paused file med preserved context.

        Args:
            tracked_file: File der skal resumes
        """
        file_path = tracked_file.file_path
        current_status = tracked_file.status

        try:
            # Map paused status tilbage til active status
            if current_status == FileStatus.PAUSED_IN_QUEUE:
                new_status = FileStatus.IN_QUEUE
            elif current_status == FileStatus.PAUSED_COPYING:
                new_status = (
                    FileStatus.READY
                )  # Will be requeued and resume via checksum
            elif current_status == FileStatus.PAUSED_GROWING_COPY:
                new_status = (
                    FileStatus.READY
                )  # Will be requeued and resume via checksum
            else:
                logging.warning(
                    f"⚠️ Unknown paused status for {file_path}: {current_status}"
                )
                return

            # Resume med preserved context (bytes_copied bevares) - UUID precision
            await self.state_manager.update_file_status_by_id(
                file_id=tracked_file.id,  # Precise UUID reference
                status=new_status,
                error_message=None,
                retry_count=0,  # Reset retry count for fresh resume attempt
                # Note: bytes_copied og copy_progress bevares fra pause
            )

            logging.info(
                f"▶️ RESUMED: {file_path} ({current_status} → {new_status}) "
                f"- preserved {tracked_file.bytes_copied:,} bytes"
            )

        except Exception as e:
            logging.error(f"❌ Error resuming {file_path}: {e}")

    async def _get_recent_network_failed_files(self) -> List[TrackedFile]:
        """
        Get FAILED files from recent time that might be network-related.

        Returns:
            List of TrackedFile objects that failed recently and might be network issues
        """
        from datetime import datetime, timedelta

        # Look for files that failed in the last 5 minutes
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
        """
        Check if a FAILED file is likely due to network/destination issues.

        Args:
            tracked_file: TrackedFile to check

        Returns:
            True if failure appears to be network-related
        """
        error_msg = (tracked_file.error_message or "").lower()

        # Look for network error indicators in error message
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
