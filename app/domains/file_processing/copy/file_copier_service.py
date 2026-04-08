import asyncio
import logging

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
        self._workers: list[asyncio.Task[None]] = []
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
        logging.info("Stopping copy workers — waiting for current jobs to finish...")

        # Give workers up to N seconds to finish their current job gracefully
        if self._workers:
            _, pending = await asyncio.wait(
                self._workers, timeout=self.settings.graceful_shutdown_timeout_seconds
            )
            if pending:
                logging.warning(
                    f"{len(pending)} workers still busy after grace period — cancelling"
                )
                for worker in pending:
                    worker.cancel()
                await asyncio.gather(*pending, return_exceptions=True)

        self._workers.clear()
        logging.info("All copy workers stopped")

    async def resize_pool(self, new_count: int) -> None:
        """Resize the worker pool to *new_count* while running.

        - If new_count > current: spawn additional workers.
        - If new_count < current: cancel excess workers (LIFO).
        - If not running or same count: no-op.
        """
        if not self._running or new_count == len(self._workers):
            return
        new_count = max(1, new_count)
        old_count = len(self._workers)

        if new_count > old_count:
            for i in range(old_count, new_count):
                task = asyncio.create_task(
                    self._worker_loop(f"worker-{i + 1}"),
                    name=f"copy-worker-{i + 1}",
                )
                self._workers.append(task)
        else:
            excess = self._workers[new_count:]
            self._workers = self._workers[:new_count]
            for task in excess:
                task.cancel()
            await asyncio.gather(*excess, return_exceptions=True)

        self._worker_count = new_count
        logging.info("Copy worker pool resized: %d → %d", old_count, new_count)

    async def _worker_loop(self, worker_id: str) -> None:
        try:
            while self._running:
                job = await self.job_queue.get_next_job()
                if job is None:
                    await asyncio.sleep(1)
                    continue

                try:
                    command = ProcessJobCommand(job=job)
                    await self.command_bus.execute(command)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logging.error(
                        f"Worker {worker_id} failed processing job {job.file_path}: "
                        f"{type(e).__name__}: {e}",
                        exc_info=True,
                    )

        except asyncio.CancelledError:
            logging.debug(f"Worker {worker_id} cancelled")
            raise

