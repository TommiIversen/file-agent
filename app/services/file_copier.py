import asyncio
import logging
from typing import Dict, Optional, List
from dataclasses import dataclass
from pathlib import Path

from app.services.job_queue import JobQueueService
from app.services.consumer.job_processor import JobProcessor
from app.services.consumer.job_error_classifier import JobErrorClassifier
from app.services.copy.file_copy_executor import FileCopyExecutor
from app.services.copy_strategies import CopyStrategyFactory
from app.services.tracking.copy_statistics import CopyStatisticsTracker
from app.services.error_handling.copy_error_handler import CopyErrorHandler
from app.services.destination.destination_checker import DestinationChecker


@dataclass
class FileCopyServiceConfig:
    """Configuration for FileCopyService."""
    max_concurrent_copies: int = 1
    source_path: str = ""
    destination_path: str = ""


class FileCopyService:   
    def __init__(
        self,
        settings,
        state_manager,
        job_queue: JobQueueService,
        copy_strategy_factory: Optional[CopyStrategyFactory] = None,
        statistics_tracker: Optional[CopyStatisticsTracker] = None,
        error_handler: Optional[CopyErrorHandler] = None,
        destination_checker: Optional[DestinationChecker] = None,
        space_checker=None,
        space_retry_manager=None,
        storage_monitor=None,
        enable_resume: bool = True
    ):
        self._logger = logging.getLogger(self.__class__.__name__)
        self._running = False
        self._consumer_tasks: List[asyncio.Task] = []
        self._max_concurrent_copies = settings.max_concurrent_copies
        
        # Store settings for backward compatibility
        self.settings = settings
        self._destination_available = True  # For test compatibility
        
        # Core services - all operations delegated to these
        self.job_queue = job_queue
        self.copy_strategy_factory = copy_strategy_factory or CopyStrategyFactory(
            settings, state_manager, enable_resume=enable_resume
        )
        self.statistics_tracker = statistics_tracker or CopyStatisticsTracker(settings, enable_session_tracking=True)
        self.error_handler = error_handler or CopyErrorHandler(settings)
        self.destination_checker = destination_checker or DestinationChecker(
            Path(settings.destination_directory), 
            storage_monitor=storage_monitor
        )
        
        # Composed services
        self.file_copy_executor = FileCopyExecutor(settings)
        
        # Create error classifier if storage monitor is available
        error_classifier = JobErrorClassifier(storage_monitor) if storage_monitor else None
        
        self.job_processor = JobProcessor(
            settings=settings,
            state_manager=state_manager,
            job_queue=job_queue,
            copy_strategy_factory=self.copy_strategy_factory,
            space_checker=space_checker,
            space_retry_manager=space_retry_manager
        )
        
        # Inject error classifier into copy executor
        if error_classifier and hasattr(self.job_processor, 'copy_executor'):
            self.job_processor.copy_executor.error_classifier = error_classifier

    async def start_consumer(self) -> None:
        """Start consumer workers."""
        if self._running:
            return
        self._running = True
        self._logger.info(f"Starting {self._max_concurrent_copies} workers")
        
        for i in range(self._max_concurrent_copies):
            task = asyncio.create_task(self._consumer_worker(i))
            self._consumer_tasks.append(task)
        
        await asyncio.gather(*self._consumer_tasks, return_exceptions=True)

    async def stop_consumer(self) -> None:
        """Stop all consumer workers."""
        self._running = False
        if self._consumer_tasks:
            for task in self._consumer_tasks:
                task.cancel()
            await asyncio.gather(*self._consumer_tasks, return_exceptions=True)
            self._consumer_tasks.clear()

    async def _consumer_worker(self, worker_id: int) -> None:
        """Worker that processes jobs from queue."""
        try:
            while self._running:
                # DECOUPLED: Let StorageMonitorService handle destination problems via pause/resume
                # Don't check destination availability here - let the intelligent error handling 
                # and pause/resume system handle it at the job level
                
                job = await self.job_queue.get_next_job()
                if job is None:
                    await asyncio.sleep(1)
                    continue
                
                await self.job_processor.process_job(job)
                
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._logger.error(f"Worker {worker_id} error: {e}")
            raise

    async def get_copy_statistics(self) -> Dict:
        """Get copy statistics."""
        stats = self.statistics_tracker.get_statistics_summary()
        errors = self.error_handler.get_error_statistics()
        
        return {
            "is_running": self._running,
            "active_workers": len([t for t in self._consumer_tasks if not t.done()]),
            "destination_available": await self.destination_checker.is_available(),
            "total_files_copied": stats.total_files_copied,
            "total_bytes_copied": stats.total_bytes_copied,
            "total_files_failed": stats.total_files_failed,
            "total_gb_copied": stats.total_gb_copied,
            "success_rate": stats.success_rate,
            "current_errors": errors.get('current_errors', 0),
            "global_errors": errors.get('global_errors', 0),
            "performance": {
                "peak_transfer_rate_mbps": stats.peak_transfer_rate_mbps
            },
            "error_handling": {
                "current_errors": errors.get('current_errors', 0),
                "global_errors": errors.get('global_errors', 0)
            }
        }

    def is_running(self) -> bool:
        """Check if consumer is running."""
        return self._running

    def get_active_worker_count(self) -> int:
        """Get count of active workers."""
        return len([t for t in self._consumer_tasks if not t.done()])