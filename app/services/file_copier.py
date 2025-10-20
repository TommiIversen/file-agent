import asyncio
import logging
from datetime import datetime
from typing import List, Optional

from app.config import Settings
from app.services.consumer.job_models import QueueJob
from app.services.consumer.job_processor import JobProcessor
from app.services.job_queue import JobQueueService
from app.services.state_manager import StateManager


class FileCopierService:

    def __init__(
            self,
            settings: Settings,
            state_manager: StateManager,
            job_queue: JobQueueService,
            job_processor: JobProcessor,
    ):
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
        self._start_time: Optional[datetime] = None

        self._destination_available = True

        logging.info(
            f"FileCopierService initialiseret med {self._worker_count} workers"
        )

    @property
    def copy_strategy_factory(self):
        return self.job_processor.copy_strategy_factory

    @property
    def file_copy_executor(self):
        return self.job_processor.copy_executor

    async def start_workers(self) -> None:
        if self._running:
            logging.warning("Workers are already running")
            return

        self._running = True
        self._start_time = datetime.now()

        for i in range(self._worker_count):
            worker_task = asyncio.create_task(
                self._worker_loop(f"worker-{i + 1}"), name=f"copy-worker-{i + 1}"
            )
            self._workers.append(worker_task)

        logging.info(f"Started {len(self._workers)} copy workers")

    async def stop_workers(self) -> None:
        if not self._running:
            return

        self._running = False
        logging.info("Stopping copy workers...")

        for worker in self._workers:
            if not worker.done():
                worker.cancel()

        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)

        self._workers.clear()
        logging.info("All copy workers stopped")

    async def _worker_loop(self, worker_id: str) -> None:
        try:
            while self._running:
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

    async def get_copy_statistics(self):
        return {
            "is_running": self._running,
            "total_files_copied": 0,
            "total_bytes_copied": 0,
            "total_files_failed": 0,
            "success_rate": 100.0,
        }

    def is_running(self):
        return self._running

    def get_active_worker_count(self):
        return 0
