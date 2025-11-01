import asyncio
import logging
from typing import List

from app.config import Settings
from app.core.cqrs.command_bus import CommandBus
from app.domains.file_processing.consumer.job_models import QueueJob
from app.domains.file_processing.commands import ProcessJobCommand
from app.domains.file_processing.job_queue import JobQueueService


class FileCopierService:
    def __init__(
        self,
        settings: Settings,
        job_queue: JobQueueService,
        command_bus: CommandBus,
    ):
        self.settings = settings
        self.job_queue = job_queue
        self.command_bus = command_bus

        # Worker management
        self._workers: List[asyncio.Task] = []
        self._running = False
        self._worker_count = settings.max_concurrent_copies

        logging.info(
            f"FileCopierService initialiseret med {self._worker_count} workers"
        )

    async def start_workers(self) -> None:
        if self._running:
            logging.warning("Workers are already running")
            return

        self._running = True

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

                # Use CQRS CommandBus instead of direct JobProcessor call
                command = ProcessJobCommand(job=job)
                await self.command_bus.execute(command)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logging.error(f"Worker {worker_id} error: {e}")
            raise

