"""
Job Processor - pure orchestrator delegating work to specialized services.
"""

import logging

from app.config import Settings
from app.services.consumer.job_copy_executor import JobCopyExecutor
from app.services.consumer.job_file_preparation_service import JobFilePreparationService
from app.services.consumer.job_finalization_service import JobFinalizationService
from app.services.consumer.job_models import ProcessResult, QueueJob
from app.services.consumer.job_space_manager import JobSpaceManager
from app.services.copy_strategies import GrowingFileCopyStrategy
from app.services.job_queue import JobQueueService
from app.services.state_manager import StateManager
from app.utils.output_folder_template import OutputFolderTemplateEngine


class JobProcessor:
    """Pure orchestrator coordinating job processing workflow across specialized services."""

    def __init__(
        self,
        settings: Settings,
        state_manager: StateManager,
        job_queue: JobQueueService,
        copy_strategy: GrowingFileCopyStrategy,
        space_checker=None,
        space_retry_manager=None,
        error_classifier=None,
        event_bus=None,
    ):
        self.settings = settings
        self.state_manager = state_manager
        self.job_queue = job_queue
        self.copy_strategy = copy_strategy

        self.space_manager = JobSpaceManager(
            settings=settings,
            state_manager=state_manager,
            job_queue=job_queue,
            space_checker=space_checker,
            space_retry_manager=space_retry_manager,
        )

        self.finalization_service = JobFinalizationService(
            settings=settings, 
            state_manager=state_manager, 
            job_queue=job_queue, 
            event_bus=event_bus
        )

        self.template_engine = OutputFolderTemplateEngine(settings)

        self.file_preparation_service = JobFilePreparationService(
            settings=settings,
            state_manager=state_manager,
            copy_strategy=copy_strategy,
            template_engine=self.template_engine,
        )

        self.copy_executor = JobCopyExecutor(
            settings=settings,
            state_manager=state_manager,
            copy_strategy=copy_strategy,
            error_classifier=error_classifier,
            event_bus=event_bus,
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
                copy_success = await self.copy_executor.execute_copy(prepared_file)

                if copy_success:
                    await self.finalization_service.finalize_success(
                        job, prepared_file.tracked_file.file_size
                    )
                    return ProcessResult(success=True, file_path=file_path)
                else:
                    logging.warning(f"Copy execution returned failure: {file_path}")
                    return ProcessResult(
                        success=False,
                        file_path=file_path,
                        error_message="Copy execution failed",
                    )

            except Exception as copy_error:
                logging.warning(f"Copy exception for {file_path}: {copy_error}")

                was_paused = await self.copy_executor.handle_copy_failure(
                    prepared_file, copy_error
                )

                if was_paused:
                    return ProcessResult(
                        success=False,
                        file_path=file_path,
                        error_message=f"Copy paused due to network issue: {copy_error}",
                        should_retry=True,
                    )
                else:
                    return ProcessResult(
                        success=False,
                        file_path=file_path,
                        error_message=f"Copy failed permanently: {copy_error}",
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
