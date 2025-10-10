"""
Job Processor Service for File Transfer Agent.

JobProcessor håndterer job processing logik fra FileCopyService:
- Space checking før kopiering
- Job preparation og validering
- File status management
- Job finalization (success/failure)
- Integration med StateManager, JobQueue, og copy strategies

Dette er en core service der extractes fra FileCopyService for at følge SOLID principper.
"""

import logging
from datetime import datetime
from typing import Dict, Optional
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.models import FileStatus, SpaceCheckResult, TrackedFile
from app.services.state_manager import StateManager
from app.services.job_queue import JobQueueService
from app.services.copy_strategies import FileCopyStrategyFactory
from app.utils.output_folder_template import OutputFolderTemplateEngine


@dataclass
class ProcessResult:
    """
    Result of a job processing operation.
    
    Provides information about job processing outcome and any errors.
    """
    success: bool
    file_path: str
    error_message: Optional[str] = None
    retry_scheduled: bool = False
    space_shortage: bool = False
    
    def get_summary(self) -> str:
        """Get a human-readable summary of the processing result."""
        if self.success:
            return f"Job processed successfully: {Path(self.file_path).name}"
        elif self.space_shortage:
            return f"Space shortage, retry scheduled: {Path(self.file_path).name}"
        else:
            return f"Job failed: {Path(self.file_path).name} - {self.error_message or 'Unknown error'}"


@dataclass
class PreparedFile:
    """
    Information about a file prepared for copying.
    
    Contains validated file information and copy strategy.
    """
    tracked_file: TrackedFile
    strategy_name: str
    initial_status: FileStatus
    destination_path: Path


class JobProcessor:
    """
    Responsible for processing copy jobs with comprehensive workflow management.
    
    Handles:
    - Pre-flight space checking
    - Job preparation and validation
    - File status management
    - Copy strategy selection
    - Job finalization and cleanup
    """
    
    def __init__(
        self, 
        settings: Settings,
        state_manager: StateManager,
        job_queue: JobQueueService,
        copy_strategy_factory: FileCopyStrategyFactory,
        space_checker=None,
        space_retry_manager=None
    ):
        """
        Initialize JobProcessor with required dependencies.
        
        Args:
            settings: Application settings
            state_manager: Central state manager
            job_queue: Job queue service
            copy_strategy_factory: Factory for copy strategies
            space_checker: Optional space checking utility
            space_retry_manager: Optional space retry manager
        """
        self.settings = settings
        self.state_manager = state_manager
        self.job_queue = job_queue
        self.copy_strategy_factory = copy_strategy_factory
        self.space_checker = space_checker
        self.space_retry_manager = space_retry_manager
        self._logger = logging.getLogger("app.job_processor")
        
        # Initialize output folder template engine
        self.template_engine = OutputFolderTemplateEngine(settings)
        
        self._logger.debug("JobProcessor initialized")
        if self.template_engine.is_enabled():
            self._logger.info(f"Output folder template system enabled with {len(self.template_engine.rules)} rules")
    
    async def process_job(self, job: Dict) -> ProcessResult:
        """
        Process a single copy job with comprehensive workflow.
        
        Flow:
        1. Pre-flight space check (if enabled)
        2. Job preparation and validation
        3. File status initialization
        4. Return result for copy execution
        
        Args:
            job: Job dictionary from queue
            
        Returns:
            ProcessResult with job processing outcome
        """
        file_path = job["file_path"]
        
        try:
            self._logger.info(f"Processing job: {file_path}")
            
            # Step 1: Pre-flight space check (if enabled)
            if self._should_check_space():
                space_check = await self.handle_space_check(job)
                if not space_check.has_space:
                    return await self._handle_space_shortage_result(job, space_check)
            
            # Step 2: Prepare file for copying
            prepared_file = await self.prepare_file_for_copy(job)
            if not prepared_file:
                return ProcessResult(
                    success=False,
                    file_path=file_path,
                    error_message="File not found in state manager"
                )
            
            # Step 3: Initialize file status for copying
            await self._initialize_copy_status(prepared_file)
            
            # Step 4: Execute the actual copy operation
            copy_success = await self._execute_copy(prepared_file)
            
            if copy_success:
                # Step 5: Finalize successful copy
                await self.finalize_job_success(job, prepared_file.tracked_file.file_size)
                return ProcessResult(success=True, file_path=file_path)
            else:
                # Copy failed
                await self.state_manager.update_file_status(
                    file_path,
                    FileStatus.FAILED,
                    copy_progress=0.0,
                    bytes_copied=0,
                    error_message="Copy operation failed"
                )
                return ProcessResult(
                    success=False,
                    file_path=file_path,
                    error_message="Copy operation failed"
                )
            
        except Exception as e:
            self._logger.error(f"Unexpected error processing job {file_path}: {e}")
            return ProcessResult(
                success=False,
                file_path=file_path,
                error_message=f"Unexpected error: {str(e)}"
            )
    
    async def handle_space_check(self, job: Dict) -> SpaceCheckResult:
        """
        Perform space check for a job.
        
        Args:
            job: Job dictionary containing file info
            
        Returns:
            SpaceCheckResult with space availability information
        """
        if not self.space_checker:
            # If no space checker available, assume space is available
            file_size = job.get("file_size", 0)
            return SpaceCheckResult(
                has_space=True, 
                available_bytes=0,  # Unknown when no checker
                required_bytes=file_size,
                file_size_bytes=file_size,
                safety_margin_bytes=0,
                reason="No space checker configured"
            )
        
        # Get file size from job or tracked file
        file_size = job.get("file_size", 0)
        
        if file_size == 0:
            # Fallback: get from tracked file
            tracked_file = await self.state_manager.get_file(job["file_path"])
            if tracked_file:
                file_size = tracked_file.file_size
        
        return self.space_checker.check_space_for_file(file_size)
    
    async def prepare_file_for_copy(self, job: Dict) -> Optional[PreparedFile]:
        """
        Prepare file information for copying with strategy selection.
        
        Args:
            job: Job dictionary
            
        Returns:
            PreparedFile with validated information, or None if file not found
        """
        file_path = job["file_path"]
        
        # Get tracked file from state manager
        tracked_file = await self.state_manager.get_file(file_path)
        if not tracked_file:
            self._logger.error(f"File not found in state manager: {file_path}")
            return None
        
        # Select appropriate copy strategy
        strategy = self.copy_strategy_factory.get_strategy(tracked_file)
        strategy_name = strategy.__class__.__name__
        
        # Determine initial status based on strategy
        if strategy_name == "GrowingFileCopyStrategy":
            initial_status = FileStatus.GROWING_COPY
        else:
            initial_status = FileStatus.COPYING
        
        # Calculate destination path using template engine if enabled
        from app.utils.file_operations import build_destination_path_with_template, generate_conflict_free_path
        
        source = Path(file_path)
        source_base = Path(self.settings.source_directory)
        dest_base = Path(self.settings.destination_directory)
        
        # Use template engine for path generation
        dest_path = build_destination_path_with_template(
            source, source_base, dest_base, self.template_engine
        )
        destination_path = generate_conflict_free_path(Path(dest_path))
        
        return PreparedFile(
            tracked_file=tracked_file,
            strategy_name=strategy_name,
            initial_status=initial_status,
            destination_path=destination_path
        )
    
    async def finalize_job_success(self, job: Dict, file_size: int) -> None:
        """
        Finalize successful job completion.
        
        Args:
            job: Job dictionary
            file_size: Final file size for statistics
        """
        file_path = job["file_path"]
        
        try:
            # Mark job as completed in queue
            await self.job_queue.mark_job_completed(job)
            
            # Update file status to completed
            await self.state_manager.update_file_status(
                file_path,
                FileStatus.COMPLETED,
                copy_progress=100.0,
                error_message=None,
                retry_count=0
            )
            
            self._logger.info(f"Job completed successfully: {file_path}")
            
        except Exception as e:
            self._logger.error(f"Error finalizing successful job {file_path}: {e}")
    
    async def finalize_job_failure(self, job: Dict, error: Exception) -> None:
        """
        Finalize failed job with error handling.
        
        Args:
            job: Job dictionary
            error: Exception that caused the failure
        """
        file_path = job["file_path"]
        error_message = str(error)
        
        try:
            # Mark job as failed in queue
            await self.job_queue.mark_job_failed(job, error_message)
            
            # Update file status to failed
            await self.state_manager.update_file_status(
                file_path,
                FileStatus.FAILED,
                error_message=error_message
            )
            
            self._logger.error(f"Job failed permanently: {file_path} - {error_message}")
            
        except Exception as e:
            self._logger.error(f"Error finalizing failed job {file_path}: {e}")
    
    async def finalize_job_max_retries(self, job: Dict) -> None:
        """
        Finalize job that failed after maximum retry attempts.
        
        Args:
            job: Job dictionary
        """
        file_path = job["file_path"]
        error_message = f"Failed after {self.settings.max_retry_attempts} retry attempts"
        
        try:
            # Mark job as failed in queue
            await self.job_queue.mark_job_failed(job, "Max retry attempts reached")
            
            # Update file status to failed
            await self.state_manager.update_file_status(
                file_path,
                FileStatus.FAILED,
                error_message=error_message
            )
            
            self._logger.error(f"Job failed after max retries: {file_path}")
            
        except Exception as e:
            self._logger.error(f"Error finalizing job after max retries {file_path}: {e}")
    
    async def _initialize_copy_status(self, prepared_file: PreparedFile) -> None:
        """
        Initialize file status for copying operation.
        
        Args:
            prepared_file: Prepared file information
        """
        await self.state_manager.update_file_status(
            prepared_file.tracked_file.file_path, 
            prepared_file.initial_status,
            copy_progress=0.0,
            started_copying_at=datetime.now()
        )
        
        self._logger.debug(
            f"Initialized copy status for {prepared_file.tracked_file.file_path} "
            f"with strategy {prepared_file.strategy_name}"
        )
    
    async def _execute_copy(self, prepared_file: PreparedFile) -> bool:
        """
        Execute the actual copy operation using the selected strategy.
        
        Args:
            prepared_file: Prepared file information with strategy
            
        Returns:
            True if copy was successful, False otherwise
        """
        try:
            # Get the copy strategy for this file
            strategy = self.copy_strategy_factory.get_strategy(prepared_file.tracked_file)
            
            # Execute the copy operation with progress tracking
            self._logger.info(
                f"Starting copy with {strategy.__class__.__name__}: "
                f"{prepared_file.tracked_file.file_path} -> {prepared_file.destination_path}"
            )
            
            copy_success = await strategy.copy_file(
                prepared_file.tracked_file.file_path,
                str(prepared_file.destination_path),
                prepared_file.tracked_file
            )
            
            if copy_success:
                self._logger.info(f"Copy completed successfully: {prepared_file.tracked_file.file_path}")
            else:
                self._logger.error(f"Copy failed: {prepared_file.tracked_file.file_path}")
            
            return copy_success
            
        except Exception as e:
            self._logger.error(f"Error executing copy for {prepared_file.tracked_file.file_path}: {e}")
            return False
    
    async def _handle_space_shortage_result(self, job: Dict, space_check: SpaceCheckResult) -> ProcessResult:
        """
        Handle space shortage by scheduling retry or marking as failed.
        
        Args:
            job: Job that couldn't be processed due to space
            space_check: Result of space check
            
        Returns:
            ProcessResult indicating space shortage handling
        """
        file_path = job["file_path"]
        
        self._logger.warning(
            f"Insufficient space for {file_path}: {space_check.reason}",
            extra={
                "operation": "space_shortage",
                "file_path": file_path,
                "available_gb": space_check.get_available_gb(),
                "required_gb": space_check.get_required_gb(),
                "shortage_gb": space_check.get_shortage_gb()
            }
        )
        
        # Use SpaceRetryManager if available, otherwise mark as failed
        if self.space_retry_manager:
            try:
                await self.space_retry_manager.schedule_space_retry(file_path, space_check)
                return ProcessResult(
                    success=False,
                    file_path=file_path,
                    error_message=f"Insufficient space: {space_check.reason}",
                    retry_scheduled=True,
                    space_shortage=True
                )
            except Exception as e:
                self._logger.error(f"Error scheduling space retry for {file_path}: {e}")
        
        # Fallback: mark as failed if no retry manager or retry scheduling failed
        try:
            await self.state_manager.update_file_status(
                file_path,
                FileStatus.FAILED,
                error_message=f"Insufficient space: {space_check.reason}"
            )
            await self.job_queue.mark_job_failed(job, "Insufficient disk space")
        except Exception as e:
            self._logger.error(f"Error marking job as failed due to space shortage {file_path}: {e}")
        
        return ProcessResult(
            success=False,
            file_path=file_path,
            error_message=f"Insufficient space: {space_check.reason}",
            space_shortage=True
        )
    
    def _should_check_space(self) -> bool:
        """
        Check if space checking should be performed.
        
        Returns:
            True if space checking is enabled and space checker is available
        """
        return (
            self.settings.enable_pre_copy_space_check and 
            self.space_checker is not None
        )
    
    def get_processor_info(self) -> dict:
        """
        Get information about the job processor configuration.
        
        Returns:
            Dictionary with processor configuration details
        """
        return {
            "space_checking_enabled": self._should_check_space(),
            "max_retry_attempts": self.settings.max_retry_attempts,
            "space_retry_manager_available": self.space_retry_manager is not None,
            "copy_strategies_available": len(self.copy_strategy_factory.get_available_strategies())
        }