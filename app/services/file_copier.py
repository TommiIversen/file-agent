"""
File Copier Service for File Transfer Agent.

FileCopierService håndterer consumer-siden af producer/consumer pattern.
Dette er hovedservice der tager jobs fra queue og orkesterer copy operationer.

ARCHITECTURE FOCUS:
- Consumer-only responsibility (no destination monitoring logic)
- Uses JobProcessor for actual copy orchestration
- Decoupled from destination availability checking (StorageMonitorService handles this)
- Focus on job processing efficiency and error handling
"""

import asyncio
import logging
from typing import List, Optional
from datetime import datetime

from app.config import Settings
from app.services.state_manager import StateManager
from app.services.job_queue import JobQueueService
from app.services.consumer.job_processor import JobProcessor
from app.services.consumer.job_models import QueueJob


class FileCopierService:
    """
    File copier service - consumer i producer/consumer systemet.

    Ansvar:
    1. Pull jobs fra JobQueueService
    2. Orkestrer copy operations via JobProcessor
    3. Håndter worker management og concurrency
    4. Provide statistics og monitoring

    DECOUPLED DESIGN:
    - Destination availability handled by StorageMonitorService (pause/resume)
    - No destination checking logic here - pure job processing
    """

    def __init__(
        self,
        settings: Settings,
        state_manager: StateManager,
        job_queue: JobQueueService,
        job_processor: JobProcessor,
    ):
        """
        Initialize FileCopierService.

        Args:
            settings: Application settings
            state_manager: Central state manager
            job_queue: Job queue service
            job_processor: Job processor for copy operations
        """
        self.settings = settings
        self.state_manager = state_manager
        self.job_queue = job_queue
        self.job_processor = job_processor

        # Worker management
        self._workers: List[asyncio.Task] = []
        self._running = False
        self._worker_count = settings.max_concurrent_copies

        # Statistics
        self._total_jobs_processed = 0
        self._total_jobs_failed = 0
        self._start_time: Optional[datetime] = None

        # Legacy compatibility attributes
        self._destination_available = True

        logging.info(
            f"FileCopierService initialiseret med {self._worker_count} workers"
        )

    @property
    def copy_strategy_factory(self):
        """Expose JobProcessor's copy_strategy_factory for compatibility."""
        return self.job_processor.copy_strategy_factory

    @property
    def file_copy_executor(self):
        """Expose JobProcessor's copy_executor as file_copy_executor for compatibility."""
        return self.job_processor.copy_executor

    async def start_workers(self) -> None:
        """Start copy worker tasks."""
        if self._running:
            logging.warning("Workers are already running")
            return

        self._running = True
        self._start_time = datetime.now()

        # Start worker tasks
        for i in range(self._worker_count):
            worker_task = asyncio.create_task(
                self._worker_loop(f"worker-{i + 1}"), name=f"copy-worker-{i + 1}"
            )
            self._workers.append(worker_task)

        logging.info(f"Started {len(self._workers)} copy workers")

    async def stop_workers(self) -> None:
        """Stop all copy workers gracefully."""
        if not self._running:
            return

        self._running = False
        logging.info("Stopping copy workers...")

        # Cancel all worker tasks
        for worker in self._workers:
            if not worker.done():
                worker.cancel()

        # Wait for workers to finish
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)

        self._workers.clear()
        logging.info("All copy workers stopped")

    async def _worker_loop(self, worker_id: str) -> None:
        """Worker that processes jobs from queue."""
        try:
            while self._running:
                # DECOUPLED: Let StorageMonitorService handle destination problems via pause/resume
                # Don't check destination availability here - let the intelligent error handling
                # and pause/resume system handle it at the job level

                job: QueueJob = await self.job_queue.get_next_job()
                if job is None:
                    await asyncio.sleep(1)
                    continue

                await self.job_processor.process_job(job)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logging.error(f"Worker {worker_id} error: {e}")
            raise

    # Legacy compatibility methods
    async def get_copy_statistics(self):
        """Legacy method for backwards compatibility - get copy statistics."""
        return {
            "is_running": self._running,
            "total_files_copied": 0,
            "total_bytes_copied": 0,
            "total_files_failed": 0,
            "success_rate": 100.0,
        }

    def is_running(self):
        """Legacy method for backwards compatibility - check if service is running."""
        return self._running

    def get_active_worker_count(self):
        """Legacy method for backwards compatibility - get active worker count."""
        return 0
