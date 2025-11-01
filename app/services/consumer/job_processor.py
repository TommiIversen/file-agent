"""
Job Processor - pure orchestrator delegating work to specialized services.
"""

import logging

from app.config import Settings
from app.core.file_repository import FileRepository
from app.core.events.event_bus import DomainEventBus
from app.services.consumer.job_copy_executor import JobCopyExecutor
from app.services.consumer.job_file_preparation_service import JobFilePreparationService
from app.services.consumer.job_finalization_service import JobFinalizationService
from app.services.consumer.job_models import ProcessResult, QueueJob
from app.services.consumer.job_space_manager import JobSpaceManager
from app.services.copy.growing_copy import GrowingFileCopyStrategy
from app.services.job_queue import JobQueueService
from app.utils.output_folder_template import OutputFolderTemplateEngine


class JobProcessor:
    """Pure orchestrator coordinating job processing workflow across specialized services."""

    def __init__(
        self,
        settings: Settings,
        file_repository: FileRepository,
        event_bus: DomainEventBus,
        job_queue: JobQueueService,
        copy_strategy: GrowingFileCopyStrategy,
        finalization_service: JobFinalizationService,
        copy_executor: JobCopyExecutor,
        space_manager: JobSpaceManager,
        space_checker=None,
        space_retry_manager=None,
        error_classifier=None,
    ):
        self.settings = settings
        self.file_repository = file_repository
        self.event_bus = event_bus
        self.job_queue = job_queue
        self.copy_strategy = copy_strategy
        self.finalization_service = finalization_service
        self.copy_executor = copy_executor
        self.space_manager = space_manager

        self.template_engine = OutputFolderTemplateEngine(settings)

        self.file_preparation_service = JobFilePreparationService(
            settings=settings,
            file_repository=file_repository,
            event_bus=event_bus,
            copy_strategy=copy_strategy,
            template_engine=self.template_engine,
        )

        logging.debug("JobProcessor initialized")
        if self.template_engine.is_enabled():
            logging.info(
                f"Output folder template system enabled with {len(self.template_engine.rules)} rules"
            )

    async def process_job(self, job: QueueJob) -> ProcessResult:
        """Process a single copy job through the complete workflow."""
        file_path = job.file_path

        try:
            logging.info(f"Processing job: {file_path}")

            if self.space_manager.should_check_space():
                space_check = await self.space_manager.check_space_for_job(job)
                if not space_check.has_space:
                    return await self.space_manager.handle_space_shortage(
                        job, space_check
                    )

            prepared_file = await self.file_preparation_service.prepare_file_for_copy(
                job
            )
            if not prepared_file:
                return ProcessResult(
                    success=False,
                    file_path=file_path,
                    error_message="File not found in state manager",
                )

            await self.copy_executor.initialize_copy_status(prepared_file)

            try:
                await self.copy_executor.execute_copy(prepared_file)
                await self.finalization_service.finalize_success(
                    job, prepared_file.job.file_size
                )
                # Mark job as completed in queue after successful finalization
                await self.job_queue.mark_job_completed(job)
                return ProcessResult(success=True, file_path=file_path)

            except Exception as copy_error:
                logging.warning(f"Copy exception for {file_path}: {copy_error}")

                await self.copy_executor.handle_copy_failure(
                    prepared_file, copy_error
                )

                # The JobErrorClassifier will have set the appropriate status (FAILED, REMOVED, etc.)
                # The JobProcessor now just needs to return a ProcessResult indicating failure.
                # If a retry is desired, JobErrorClassifier should set a status that triggers retry logic elsewhere, or
                # JobCopyExecutor.handle_copy_failure should return a more explicit retry instruction.
                # For now, assuming all exceptions lead to a FAILED status unless explicitly handled as REMOVED by classifier.
                return ProcessResult(
                    success=False,
                    file_path=file_path,
                    error_message=f"Copy operation failed: {copy_error}",
                    # should_retry=... (This logic needs to be refined based on JobErrorClassifier output)
                )

        except Exception as e:
            logging.error(f"Unexpected error processing job {file_path}: {e}")
            return ProcessResult(
                success=False,
                file_path=file_path,
                error_message=f"Unexpected error: {str(e)}",
            )

    def get_processor_info(self) -> dict:
        """Get information about the job processor configuration."""
        return {
            "space_manager": self.space_manager.get_space_manager_info(),
            "finalization_service": self.finalization_service.get_finalization_info(),
            "file_preparation_service": self.file_preparation_service.get_preparation_info(),
            "copy_executor": self.copy_executor.get_copy_executor_info(),
        }
