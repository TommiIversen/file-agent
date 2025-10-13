"""
Job Copy Executor Service for File Transfer Agent.

Responsible solely for copy execution operations and status initialization.
Extracted from JobProcessor to complete the transformation into a pure orchestrator.

This service handles:
- Copy status initialization for operations
- Copy strategy execution with progress tracking
- Resume scenario detection and logging
- Copy operation logging and metrics
- Intelligent error handling with pause vs fail classification
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import Settings
from app.models import FileStatus
from app.services.state_manager import StateManager
from app.services.copy_strategies import CopyStrategyFactory
from app.services.consumer.job_models import PreparedFile
from app.services.consumer.job_error_classifier import JobErrorClassifier


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
        copy_strategy_factory: CopyStrategyFactory,
        error_classifier: Optional[JobErrorClassifier] = None,
    ):
        """
        Initialize JobCopyExecutor with required dependencies.

        Args:
            settings: Application settings
            state_manager: Central state manager for status updates
            copy_strategy_factory: Factory for copy strategy selection
            error_classifier: Optional error classifier for intelligent handling
        """
        self.settings = settings
        self.state_manager = state_manager
        self.copy_strategy_factory = copy_strategy_factory
        self.error_classifier = error_classifier

        logging.debug("JobCopyExecutor initialized")

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
            started_copying_at=datetime.now(),
        )

        logging.debug(
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
            strategy = self.copy_strategy_factory.get_strategy(
                prepared_file.tracked_file
            )

            # Check if destination exists for resume detection logging
            dest_path = Path(str(prepared_file.destination_path))
            source_path = Path(prepared_file.tracked_file.file_path)

            dest_exists = dest_path.exists()
            if dest_exists:
                dest_size = dest_path.stat().st_size
                source_size = source_path.stat().st_size
                completion_pct = (
                    (dest_size / source_size) * 100 if source_size > 0 else 0
                )

                logging.info(
                    f"RESUME SCENARIO DETECTED: {dest_path.name} "
                    f"({dest_size:,}/{source_size:,} bytes = {completion_pct:.1f}% complete)"
                )

                # Check if strategy has resume capabilities
                strategy_name = strategy.__class__.__name__
                if "Resumable" in strategy_name:
                    logging.info(f"Using RESUME-CAPABLE strategy: {strategy_name}")
                else:
                    logging.warning(
                        f"Using NON-RESUMABLE strategy: {strategy_name} - will restart from beginning!"
                    )
            else:
                logging.info("FRESH COPY: No existing destination file")

            # Execute the copy operation with progress tracking
            logging.info(
                f"Starting copy with {strategy.__class__.__name__}: "
                f"{prepared_file.tracked_file.file_path} -> {prepared_file.destination_path}"
            )

            copy_success = await strategy.copy_file(
                prepared_file.tracked_file.file_path,
                str(prepared_file.destination_path),
                prepared_file.tracked_file,
            )

            if copy_success:
                logging.info(
                    f"Copy completed successfully: {prepared_file.tracked_file.file_path}"
                )

                # Log resume metrics if available
                if hasattr(strategy, "get_resume_metrics") and dest_exists:
                    metrics = strategy.get_resume_metrics()
                    if metrics:
                        logging.info(
                            f"RESUME METRICS: {dest_path.name} - "
                            f"preserved {metrics.preservation_percentage:.1f}% of data, "
                            f"verification took {metrics.verification_time_seconds:.2f}s"
                        )
            else:
                logging.error(f"Copy failed: {prepared_file.tracked_file.file_path}")

                # Log resume failure context if applicable
                if dest_exists:
                    logging.error(
                        f"RESUME FAILURE: Could not resume {dest_path.name} - may need fresh copy"
                    )

            return copy_success

        except Exception as e:
            logging.error(
                f"Error executing copy for {prepared_file.tracked_file.file_path}: {e}"
            )
            return False

    async def handle_copy_failure(
        self, prepared_file: PreparedFile, error: Exception
    ) -> bool:
        """
        Handle copy failure with intelligent error classification.

        Args:
            prepared_file: Prepared file information
            error: The original exception that caused the failure

        Returns:
            True if error was classified for pause (should retry later)
            False if error was classified for immediate failure
        """
        file_path = prepared_file.tracked_file.file_path

        # Use intelligent error classification if available
        if self.error_classifier:
            should_pause, reason = self.error_classifier.classify_copy_error(
                error, file_path
            )

            if should_pause:
                # Network/destination error - pause for later resume
                await self._handle_pause_error(prepared_file, reason, error)
                return True
            else:
                # Local/source error - fail immediately
                await self._handle_fail_error(prepared_file, reason, error)
                return False
        else:
            # Fallback: treat all errors as failures (original behavior)
            await self._handle_fail_error(prepared_file, "Copy operation failed", error)
            return False

    async def _handle_pause_error(
        self, prepared_file: PreparedFile, reason: str, error: Exception
    ) -> None:
        """
        Handle errors that should trigger pause instead of failure.

        Args:
            prepared_file: Prepared file information
            reason: Reason for pause classification
            error: Original exception
        """
        file_path = prepared_file.tracked_file.file_path
        current_tracked = await self.state_manager.get_file(file_path)

        if current_tracked:
            # Determine appropriate paused status based on current status
            current_status = current_tracked.status
            if current_status == FileStatus.COPYING:
                paused_status = FileStatus.PAUSED_COPYING
            elif current_status == FileStatus.GROWING_COPY:
                paused_status = FileStatus.PAUSED_GROWING_COPY
            else:
                paused_status = FileStatus.PAUSED_COPYING  # Default

            # Pause with preserved progress (don't reset bytes_copied or copy_progress)
            await self.state_manager.update_file_status(
                file_path,
                paused_status,
                error_message=f"Paused: {reason}",
                # Note: bytes_copied and copy_progress are preserved automatically
            )

            logging.warning(
                f"⏸️ COPY PAUSED: {Path(file_path).name} - {reason} "
                f"(preserved {current_tracked.bytes_copied or 0:,} bytes)"
            )
        else:
            # Fallback to failure if we can't get current state
            await self._handle_fail_error(
                prepared_file, f"Pause failed - {reason}", error
            )

    async def _handle_fail_error(
        self, prepared_file: PreparedFile, reason: str, error: Exception
    ) -> None:
        """
        Handle errors that should result in immediate failure.

        Args:
            prepared_file: Prepared file information
            reason: Reason for failure classification
            error: Original exception
        """
        file_path = prepared_file.tracked_file.file_path

        await self.state_manager.update_file_status(
            file_path,
            FileStatus.FAILED,
            copy_progress=0.0,
            bytes_copied=0,
            error_message=f"Failed: {reason}",
        )

        logging.error(
            f"❌ COPY FAILED: {Path(file_path).name} - {reason} (Original error: {error})"
        )

    def get_copy_executor_info(self) -> dict:
        """
        Get information about the copy executor configuration.

        Returns:
            Dictionary with copy executor configuration details
        """
        return {
            "copy_strategies_available": len(
                self.copy_strategy_factory.get_available_strategies()
            ),
            "state_manager_available": self.state_manager is not None,
            "copy_strategy_factory_available": self.copy_strategy_factory is not None,
        }
