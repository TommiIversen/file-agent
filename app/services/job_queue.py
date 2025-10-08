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
from typing import Optional, Dict, List
from datetime import datetime

from app.config import Settings
from app.models import FileStatus
from app.services.state_manager import StateManager


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
        self.job_queue: Optional[asyncio.Queue] = None  # Will be created when needed
        self._logger = logging.getLogger("app.job_queue")
        
        # Queue statistics
        self._total_jobs_added = 0
        self._total_jobs_processed = 0
        self._failed_jobs: List[Dict] = []
        
        # Queue management
        self._running = False
        self._producer_task: Optional[asyncio.Task] = None
        
        self._logger.info("JobQueueService initialiseret")
        self._logger.info("Queue vil blive oprettet når start_producer kaldes")
    
    async def start_producer(self) -> None:
        """
        Start producer task der lytter på Ready filer og tilføjer til queue.
        
        Producer task lytter på StateManager events og tilføjer filer
        med status READY til job queue automatisk.
        """
        if self._running:
            self._logger.warning("Producer task er allerede startet")
            return
        
        # Create queue if not exists
        if self.job_queue is None:
            self.job_queue = asyncio.Queue()
            self._logger.info("Queue oprettet med kapacitet: unlimited")
        
        self._running = True
        
        # Subscribe til StateManager events
        self.state_manager.subscribe(self._handle_state_change)
        
        self._logger.info("Job Queue Producer startet")
        
        try:
            # Producer kører indefinitely og lytter på events
            while self._running:
                await asyncio.sleep(1)  # Keep alive loop
                
        except asyncio.CancelledError:
            self._logger.info("Job Queue Producer blev cancelled")
            raise
        except Exception as e:
            self._logger.error(f"Fejl i producer task: {e}")
            raise
        finally:
            self._running = False
            self._logger.info("Job Queue Producer stoppet")
    
    def stop_producer(self) -> None:
        """Stop producer task gracefully."""
        self._running = False
        self._logger.info("Job Queue Producer stop request")
    
    async def _handle_state_change(self, update) -> None:
        """
        Handle StateManager events og tilføj Ready filer til queue.
        
        Args:
            update: FileStateUpdate event fra StateManager
        """
        try:
            # Kun interesseret i filer der bliver Ready
            if update.new_status == FileStatus.READY:
                await self._add_job_to_queue(update.tracked_file)
                
        except Exception as e:
            self._logger.error(f"Fejl ved håndtering af state change: {e}")
    
    async def _add_job_to_queue(self, tracked_file) -> None:
        """
        Tilføj fil job til queue og opdater status til InQueue.
        
        Args:
            tracked_file: TrackedFile objekt der skal kopieres
        """
        if self.job_queue is None:
            self._logger.error("Queue er ikke oprettet endnu!")
            return
            
        try:
            # Opret job objekt
            job = {
                "file_path": tracked_file.file_path,
                "file_size": tracked_file.file_size,
                "added_to_queue_at": datetime.now(),
                "retry_count": 0
            }
            
            # Tilføj til queue (non-blocking)
            await self.job_queue.put(job)
            self._total_jobs_added += 1
            
            # Opdater fil status til InQueue
            await self.state_manager.update_file_status(
                tracked_file.file_path,
                FileStatus.IN_QUEUE
            )
            
            self._logger.info(f"Job tilføjet til queue: {tracked_file.file_path}")
            self._logger.debug(f"Queue size nu: {self.job_queue.qsize()}")
            
        except asyncio.QueueFull:
            self._logger.error(f"Queue er fuld! Kan ikke tilføje: {tracked_file.file_path}")
            # Kunne implementere retry logic her
            
        except Exception as e:
            self._logger.error(f"Fejl ved tilføjelse til queue: {e}")
    
    async def get_next_job(self) -> Optional[Dict]:
        """
        Hent næste job fra queue (til brug af FileCopyService).
        
        Returns:
            Job dictionary eller None hvis queue er tom
        """
        if self.job_queue is None:
            return None
            
        try:
            # Non-blocking get med timeout
            job = await asyncio.wait_for(self.job_queue.get(), timeout=1.0)
            self._total_jobs_processed += 1
            
            self._logger.debug(f"Job hentet fra queue: {job['file_path']}")
            return job
            
        except asyncio.TimeoutError:
            # Queue er tom - ikke en fejl
            return None
            
        except Exception as e:
            self._logger.error(f"Fejl ved hentning fra queue: {e}")
            return None
    
    async def mark_job_completed(self, job: Dict) -> None:
        """
        Marker job som completed (kaldt af FileCopyService).
        
        Args:
            job: Job dictionary der blev completed
        """
        if self.job_queue is None:
            return
            
        try:
            # Marker task som done i asyncio.Queue
            self.job_queue.task_done()
            
            self._logger.debug(f"Job markeret som completed: {job['file_path']}")
            
        except Exception as e:
            self._logger.error(f"Fejl ved marking job completed: {e}")
    
    async def mark_job_failed(self, job: Dict, error_message: str) -> None:
        """
        Marker job som failed og håndter retry logic.
        
        Args:
            job: Job dictionary der fejlede
            error_message: Fejlbesked
        """
        if self.job_queue is None:
            return
            
        try:
            # Marker task som done i asyncio.Queue
            self.job_queue.task_done()
            
            # Log failure
            self._logger.warning(f"Job failed: {job['file_path']} - {error_message}")
            
            # Tilføj til failed jobs liste (kunne implementere dead letter queue)
            failed_job = {
                **job,
                "failed_at": datetime.now(),
                "error_message": error_message,
                "retry_count": job.get("retry_count", 0) + 1
            }
            self._failed_jobs.append(failed_job)
            
            # Keep only last 100 failed jobs for memory management
            if len(self._failed_jobs) > 100:
                self._failed_jobs = self._failed_jobs[-100:]
            
        except Exception as e:
            self._logger.error(f"Fejl ved marking job failed: {e}")
    
    async def requeue_job(self, job: Dict) -> None:
        """
        Put job tilbage i queue for retry.
        
        Args:
            job: Job dictionary der skal requeues
        """
        if self.job_queue is None:
            self._logger.error("Queue er ikke oprettet endnu!")
            return
            
        try:
            # Increment retry count
            job["retry_count"] = job.get("retry_count", 0) + 1
            job["requeued_at"] = datetime.now()
            
            # Put tilbage i queue
            await self.job_queue.put(job)
            
            self._logger.info(f"Job requeued (retry {job['retry_count']}): {job['file_path']}")
            
        except Exception as e:
            self._logger.error(f"Fejl ved requeue af job: {e}")
    
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
    
    async def get_queue_statistics(self) -> Dict:
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
            "queue_maxsize": self.job_queue.maxsize if self.job_queue and self.job_queue.maxsize > 0 else "unlimited"
        }
    
    async def get_failed_jobs(self) -> List[Dict]:
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
        self._logger.info(f"Cleared {count} failed jobs")
        return count
    
    async def peek_next_job(self) -> Optional[Dict]:
        """
        Se næste job i queue uden at fjerne det.
        
        Returns:
            Næste job dictionary eller None hvis tom
        """
        if self.is_queue_empty():
            return None
        
        # Dette er en begrænsning af asyncio.Queue - vi kan ikke peek
        # Men vi kan returnere en kopi af job statistikker
        return {
            "queue_size": self.get_queue_size(),
            "estimated_next_available": True
        }
    
    def get_producer_status(self) -> Dict:
        """
        Hent producer task status.
        
        Returns:
            Dictionary med producer status
        """
        return {
            "is_running": self._running,
            "task_created": self._producer_task is not None,
            "subscribed_to_state_manager": True  # Vi subscriber i start_producer
        }