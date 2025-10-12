"""
Job Copy Executor Service for File Transfer Agent.

Responsible solely for copy execution operations and status initialization.
Extracted from JobProcessor to complete the transformation into a pure orchestrator.

This service handles:
- Copy status initialization for operations
- Copy strategy execution with progress tracking
- Resume scenario detection and logging
- Copy operation logging and metrics
- Error handling during copy execution
"""

import logging
from datetime import datetime
from pathlib import Path

from app.config import Settings
from app.models import FileStatus
from app.services.state_manager import StateManager
from app.services.copy_strategies import CopyStrategyFactory
from app.services.consumer.job_models import PreparedFile


class JobCopyExecutor:
    """
    Responsible solely for copy execution and status management.
    
    This class adheres to SRP by handling only copy execution concerns
    including status initialization and copy strategy execution.
    """
    
    def __init__(
        self,
        settings: Settings,
        state_manager: StateManager,
        copy_strategy_factory: CopyStrategyFactory
    ):
        """
        Initialize JobCopyExecutor with required dependencies.
        
        Args:
            settings: Application settings
            state_manager: Central state manager for status updates
            copy_strategy_factory: Factory for copy strategy selection
        """
        self.settings = settings
        self.state_manager = state_manager
        self.copy_strategy_factory = copy_strategy_factory
        self._logger = logging.getLogger("app.job_copy_executor")
        
        self._logger.debug("JobCopyExecutor initialized")
    
    async def initialize_copy_status(self, prepared_file: PreparedFile) -> None:
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
    
    async def execute_copy(self, prepared_file: PreparedFile) -> bool:
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
            
            # Check if destination exists for resume detection logging
            dest_path = Path(str(prepared_file.destination_path))
            source_path = Path(prepared_file.tracked_file.file_path)
            
            dest_exists = dest_path.exists()
            if dest_exists:
                dest_size = dest_path.stat().st_size
                source_size = source_path.stat().st_size
                completion_pct = (dest_size / source_size) * 100 if source_size > 0 else 0
                
                self._logger.info(
                    f"RESUME SCENARIO DETECTED: {dest_path.name} "
                    f"({dest_size:,}/{source_size:,} bytes = {completion_pct:.1f}% complete)"
                )
                
                # Check if strategy has resume capabilities
                strategy_name = strategy.__class__.__name__
                if "Resumable" in strategy_name:
                    self._logger.info(f"Using RESUME-CAPABLE strategy: {strategy_name}")
                else:
                    self._logger.warning(f"Using NON-RESUMABLE strategy: {strategy_name} - will restart from beginning!")
            else:
                self._logger.info("FRESH COPY: No existing destination file")
            
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
                
                # Log resume metrics if available
                if hasattr(strategy, 'get_resume_metrics') and dest_exists:
                    metrics = strategy.get_resume_metrics()
                    if metrics:
                        self._logger.info(
                            f"RESUME METRICS: {dest_path.name} - "
                            f"preserved {metrics.preservation_percentage:.1f}% of data, "
                            f"verification took {metrics.verification_time_seconds:.2f}s"
                        )
            else:
                self._logger.error(f"Copy failed: {prepared_file.tracked_file.file_path}")
                
                # Log resume failure context if applicable
                if dest_exists:
                    self._logger.error(f"RESUME FAILURE: Could not resume {dest_path.name} - may need fresh copy")
            
            return copy_success
            
        except Exception as e:
            self._logger.error(f"Error executing copy for {prepared_file.tracked_file.file_path}: {e}")
            return False
    
    async def handle_copy_failure(self, prepared_file: PreparedFile, error_message: str) -> None:
        """
        Handle copy failure by updating file status.
        
        Args:
            prepared_file: Prepared file information
            error_message: Error message to record
        """
        await self.state_manager.update_file_status(
            prepared_file.tracked_file.file_path,
            FileStatus.FAILED,
            copy_progress=0.0,
            bytes_copied=0,
            error_message=error_message
        )
        
        self._logger.error(f"Copy failed for {prepared_file.tracked_file.file_path}: {error_message}")
    
    def get_copy_executor_info(self) -> dict:
        """
        Get information about the copy executor configuration.
        
        Returns:
            Dictionary with copy executor configuration details
        """
        return {
            "copy_strategies_available": len(self.copy_strategy_factory.get_available_strategies()),
            "state_manager_available": self.state_manager is not None,
            "copy_strategy_factory_available": self.copy_strategy_factory is not None
        }