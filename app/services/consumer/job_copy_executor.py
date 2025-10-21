"""
Job Copy Executor - handles copy execution and status management.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import Settings
from app.models import FileStatus
from app.services.consumer.job_error_classifier import JobErrorClassifier
from app.services.consumer.job_models import PreparedFile
from app.services.copy_strategies import CopyStrategyFactory
from app.services.state_manager import StateManager


class JobCopyExecutor:
    """Executes copy operations with status management and intelligent error handling."""

    def __init__(
            self,
            settings: Settings,
            state_manager: StateManager,
            copy_strategy_factory: CopyStrategyFactory,
            error_classifier: Optional[JobErrorClassifier] = None,
    ):
        self.settings = settings
        self.state_manager = state_manager
        self.copy_strategy_factory = copy_strategy_factory
        self.error_classifier = error_classifier

    async def initialize_copy_status(self, prepared_file: PreparedFile) -> None:
        """Initialize file status for copying operation."""
        await self.state_manager.update_file_status_by_id(
            prepared_file.tracked_file.id,
            prepared_file.initial_status,
            copy_progress=0.0,
            started_copying_at=datetime.now(),
        )

    async def execute_copy(self, prepared_file: PreparedFile) -> bool:
        """Execute copy operation using the selected strategy."""
        try:
            strategy = self.copy_strategy_factory.get_strategy(prepared_file.tracked_file)
            source_path = Path(prepared_file.tracked_file.file_path)
            dest_path = Path(str(prepared_file.destination_path))

            self._log_resume_scenario(source_path, dest_path, strategy)

            copy_success = await strategy.copy_file(
                str(source_path),
                str(dest_path),
                prepared_file.tracked_file,
            )

            self._log_copy_result(prepared_file, copy_success, strategy, dest_path.exists())
            return copy_success

        except Exception as e:
            logging.error(f"Copy execution error for {Path(prepared_file.tracked_file.file_path).name}: {e}")
            return False

    def _log_resume_scenario(self, source_path: Path, dest_path: Path, strategy):
        """Log resume scenario details."""
        if not dest_path.exists():
            logging.info(f"Fresh copy: {dest_path.name}")
            return

        dest_size = dest_path.stat().st_size
        source_size = source_path.stat().st_size
        completion_pct = (dest_size / source_size) * 100 if source_size > 0 else 0

        strategy_name = strategy.__class__.__name__
        is_resumable = "Resumable" in strategy_name

        logging.info(
            f"Resume scenario: {dest_path.name} "
            f"({dest_size:,}/{source_size:,} bytes = {completion_pct:.1f}%) "
            f"using {'resumable' if is_resumable else 'non-resumable'} strategy"
        )

    def _log_copy_result(self, prepared_file, success: bool, strategy, dest_existed: bool):
        """Log copy operation result with resume metrics if applicable."""
        file_name = Path(prepared_file.tracked_file.file_path).name

        if success:
            logging.info(f"Copy completed: {file_name}")
            if hasattr(strategy, "get_resume_metrics") and dest_existed:
                metrics = strategy.get_resume_metrics()
                if metrics:
                    logging.info(
                        f"Resume metrics: {file_name} - "
                        f"preserved {metrics.preservation_percentage:.1f}% of data"
                    )
        else:
            logging.error(f"Copy failed: {file_name}")

    async def handle_copy_failure(self, prepared_file: PreparedFile, error: Exception) -> bool:
        """Handle copy failure with intelligent error classification."""
        if not self.error_classifier:
            await self._handle_fail_error(prepared_file, "Copy operation failed", error)
            return False

        status, reason = self.error_classifier.classify_copy_error(
            error, prepared_file.tracked_file.file_path
        )

        if status == FileStatus.PAUSED_COPYING:
            await self._handle_pause_error(prepared_file, reason, error)
            return True
        elif status == FileStatus.REMOVED:
            await self._handle_remove_error(prepared_file, reason, error)
            return False  # File is gone, don't retry
        else:  # FileStatus.FAILED
            await self._handle_fail_error(prepared_file, reason, error)
            return False

    async def _handle_remove_error(self, prepared_file: PreparedFile, reason: str, error: Exception) -> None:
        """Handle errors where source file disappeared."""
        await self.state_manager.update_file_status_by_id(
            prepared_file.tracked_file.id,
            FileStatus.REMOVED,
            copy_progress=0.0,
            bytes_copied=0,
            error_message=f"Removed: {reason}",
        )

        file_name = Path(prepared_file.tracked_file.file_path).name
        logging.info(f"File removed during copy: {file_name} - {reason}")

    async def _handle_pause_error(self, prepared_file: PreparedFile, reason: str, error: Exception) -> None:
        """Handle errors that should trigger pause instead of failure."""
        current_tracked = await self.state_manager.get_file_by_id(prepared_file.tracked_file.id)

        if current_tracked:
            # Determine appropriate paused status
            paused_status = {
                FileStatus.COPYING: FileStatus.PAUSED_COPYING,
                FileStatus.GROWING_COPY: FileStatus.PAUSED_GROWING_COPY,
            }.get(current_tracked.status, FileStatus.PAUSED_COPYING)

            await self.state_manager.update_file_status_by_id(
                current_tracked.id,
                paused_status,
                error_message=f"Paused: {reason}",
            )

            logging.warning(
                f"Copy paused: {Path(current_tracked.file_path).name} - {reason} "
                f"(preserved {current_tracked.bytes_copied or 0:,} bytes)"
            )
        else:
            await self._handle_fail_error(prepared_file, f"Pause failed - file not found: {reason}", error)

    async def _handle_fail_error(self, prepared_file: PreparedFile, reason: str, error: Exception) -> None:
        """Handle errors that should result in immediate failure."""
        await self.state_manager.update_file_status_by_id(
            prepared_file.tracked_file.id,
            FileStatus.FAILED,
            copy_progress=0.0,
            bytes_copied=0,
            error_message=f"Failed: {reason}",
        )

        file_name = Path(prepared_file.tracked_file.file_path).name
        logging.error(f"Copy failed: {file_name} - {reason}")

    def get_copy_executor_info(self) -> dict:
        """Get copy executor configuration details."""
        return {
            "copy_strategies_available": len(self.copy_strategy_factory.get_available_strategies()),
            "state_manager_available": self.state_manager is not None,
            "copy_strategy_factory_available": self.copy_strategy_factory is not None,
        }
