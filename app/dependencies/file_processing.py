"""
File processing factories.

Job queue, copier, space checker, copy strategy.
"""
import asyncio
from typing import Optional

from app.dependencies.core import (
    _singletons,
    get_settings,
    get_command_bus,
    get_query_bus,
    get_event_bus,
    get_file_repository,
    get_file_state_machine,
)
from app.dependencies.storage import get_storage_monitor

from app.domains.file_processing.copy.file_copier_service import FileCopierService
from app.domains.file_processing.consumer.job_error_classifier import JobErrorClassifier
from app.domains.file_processing.consumer.job_copy_executor import JobCopyExecutor
from app.domains.file_processing.consumer.job_space_manager import JobSpaceManager
from app.domains.file_processing.consumer.job_finalization_service import JobFinalizationService
from app.domains.file_processing.copy.growing_copy import GrowingFileCopyStrategy
from app.domains.file_processing.copy.file_verification import FileVerificationService
from app.domains.file_processing.copy.copy_io_loop import CopyIoLoop
from app.domains.file_processing.job_queue import JobQueueService
from app.domains.file_processing.space_checker import SpaceChecker
from app.domains.file_processing.space_retry_manager import SpaceRetryManager


def get_job_queue_service() -> JobQueueService:
    if "job_queue_service" not in _singletons:
        _singletons["job_queue_service"] = JobQueueService(
            settings=get_settings(),
            file_repository=get_file_repository(),
            state_machine=get_file_state_machine(),
        )
    return _singletons["job_queue_service"]


def get_file_copier() -> FileCopierService:
    if "file_copier" not in _singletons:
        _singletons["file_copier"] = FileCopierService(
            settings=get_settings(),
            job_queue=get_job_queue_service(),
            command_bus=get_command_bus(),
        )
    return _singletons["file_copier"]


def get_space_checker() -> SpaceChecker:
    if "space_checker" not in _singletons:
        _singletons["space_checker"] = SpaceChecker(
            settings=get_settings(),
            storage_monitor=get_storage_monitor(),
        )
    return _singletons["space_checker"]


def get_space_retry_manager() -> SpaceRetryManager:
    if "space_retry_manager" not in _singletons:
        _singletons["space_retry_manager"] = SpaceRetryManager(
            settings=get_settings(),
            file_repository=get_file_repository(),
            state_machine=get_file_state_machine(),
        )
    return _singletons["space_retry_manager"]


def get_job_finalization_service() -> JobFinalizationService:
    if "job_finalization_service" not in _singletons:
        _singletons["job_finalization_service"] = JobFinalizationService(
            settings=get_settings(),
            file_repository=get_file_repository(),
            event_bus=get_event_bus(),
            state_machine=get_file_state_machine(),
        )
    return _singletons["job_finalization_service"]


def get_job_copy_executor() -> JobCopyExecutor:
    if "job_copy_executor" not in _singletons:
        _singletons["job_copy_executor"] = JobCopyExecutor(
            settings=get_settings(),
            file_repository=get_file_repository(),
            copy_strategy=get_copy_strategy(),
            state_machine=get_file_state_machine(),
            error_classifier=get_job_error_classifier(),
            event_bus=get_event_bus(),
        )
    return _singletons["job_copy_executor"]


def get_job_space_manager() -> JobSpaceManager:
    if "job_space_manager" not in _singletons:
        _singletons["job_space_manager"] = JobSpaceManager(
            settings=get_settings(),
            file_repository=get_file_repository(),
            space_checker=get_space_checker(),
            state_machine=get_file_state_machine(),
            retry_manager=get_space_retry_manager(),
            event_bus=get_event_bus(),
        )
    return _singletons["job_space_manager"]


def get_job_error_classifier() -> JobErrorClassifier:
    if "job_error_classifier" not in _singletons:
        _singletons["job_error_classifier"] = JobErrorClassifier(
            storage_monitor=get_storage_monitor(),
        )
    return _singletons["job_error_classifier"]


def get_copy_strategy() -> GrowingFileCopyStrategy:
    if "copy_strategy" not in _singletons:
        _singletons["copy_strategy"] = GrowingFileCopyStrategy(
            settings=get_settings(),
            file_repository=get_file_repository(),
            event_bus=get_event_bus(),
            state_machine=get_file_state_machine(),
            verification_service=get_file_verification_service(),
            io_loop=get_copy_io_loop(),
        )
    return _singletons["copy_strategy"]


def get_file_verification_service() -> FileVerificationService:
    if "file_verification_service" not in _singletons:
        _singletons["file_verification_service"] = FileVerificationService()
    return _singletons["file_verification_service"]


def get_copy_io_loop() -> CopyIoLoop:
    if "copy_io_loop" not in _singletons:
        _singletons["copy_io_loop"] = CopyIoLoop(
            settings=get_settings(),
            state_machine=get_file_state_machine(),
            event_bus=get_event_bus(),
        )
    return _singletons["copy_io_loop"]


async def get_job_queue() -> Optional[asyncio.Queue]:
    job_queue_service = get_job_queue_service()
    return job_queue_service.job_queue
