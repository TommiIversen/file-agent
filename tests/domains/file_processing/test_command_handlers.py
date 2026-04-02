"""
Tests for QueueFileCommandHandler and ProcessJobCommandHandler.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.domains.file_processing.command_handlers import (
    QueueFileCommandHandler,
    ProcessJobCommandHandler,
)
from app.domains.file_processing.commands import QueueFileCommand, ProcessJobCommand
from app.domains.file_processing.consumer.job_models import QueueJob
from app.core.exceptions import InvalidTransitionError
from app.models import TrackedFile, FileStatus


def _make_tracked(
    status: FileStatus = FileStatus.READY,
    file_id: str = "test-id-123",
) -> TrackedFile:
    return TrackedFile(
        id=file_id,
        file_path="/source/video.mxf",
        status=status,
        file_size=5_000_000,
        creation_time=datetime.now(),
        discovered_at=datetime.now(),
    )


def _make_job(file_id: str = "test-id-123") -> QueueJob:
    return QueueJob(
        file_id=file_id,
        file_path="/source/video.mxf",
        file_size=5_000_000,
        creation_time=datetime.now(),
        is_growing_at_queue_time=False,
        added_to_queue_at=datetime.now(),
    )


# ── QueueFileCommandHandler ─────────────────────────────────────────


class TestQueueFileCommandHandler:

    @pytest.fixture
    def deps(self):
        queue = AsyncMock()
        job_queue_service = MagicMock()
        job_queue_service.get_queue.return_value = queue

        file_repository = AsyncMock()
        state_machine = AsyncMock()
        network_coordinator = MagicMock()
        network_coordinator.is_network_available = True
        copy_strategy = MagicMock()
        copy_strategy._is_file_currently_growing.return_value = False

        handler = QueueFileCommandHandler(
            job_queue_service=job_queue_service,
            file_repository=file_repository,
            state_machine=state_machine,
            network_coordinator=network_coordinator,
            copy_strategy=copy_strategy,
        )
        return handler, state_machine, network_coordinator, queue, copy_strategy

    async def test_ready_file_is_queued(self, deps):
        handler, state_machine, _, queue, _ = deps
        tf = _make_tracked(status=FileStatus.READY)
        await handler.handle(QueueFileCommand(tracked_file=tf))

        state_machine.transition.assert_called_once_with(
            file_id=tf.id, new_status=FileStatus.IN_QUEUE
        )
        queue.put.assert_awaited_once()

    async def test_ready_to_start_growing_is_queued(self, deps):
        handler, state_machine, _, queue, _ = deps
        tf = _make_tracked(status=FileStatus.READY_TO_START_GROWING)
        await handler.handle(QueueFileCommand(tracked_file=tf))

        state_machine.transition.assert_called_once()
        queue.put.assert_awaited_once()

    async def test_wrong_status_ignored(self, deps):
        handler, state_machine, _, queue, _ = deps
        tf = _make_tracked(status=FileStatus.COPYING)
        await handler.handle(QueueFileCommand(tracked_file=tf))

        state_machine.transition.assert_not_called()
        queue.put.assert_not_awaited()

    async def test_network_unavailable_transitions_to_waiting(self, deps):
        handler, state_machine, network_coordinator, queue, _ = deps
        network_coordinator.is_network_available = False
        tf = _make_tracked(status=FileStatus.READY)

        await handler.handle(QueueFileCommand(tracked_file=tf))

        state_machine.transition.assert_called_once_with(
            file_id=tf.id,
            new_status=FileStatus.WAITING_FOR_NETWORK,
            error_message="Network unavailable - waiting for recovery",
        )
        queue.put.assert_not_awaited()

    async def test_network_transition_error_handled(self, deps):
        handler, state_machine, network_coordinator, queue, _ = deps
        network_coordinator.is_network_available = False
        state_machine.transition.side_effect = InvalidTransitionError("f", "READY", "WAITING_FOR_NETWORK")
        tf = _make_tracked(status=FileStatus.READY)

        # Should not raise
        await handler.handle(QueueFileCommand(tracked_file=tf))
        queue.put.assert_not_awaited()

    async def test_state_transition_error_on_in_queue(self, deps):
        handler, state_machine, _, queue, _ = deps
        state_machine.transition.side_effect = InvalidTransitionError("f", "READY", "IN_QUEUE")
        tf = _make_tracked(status=FileStatus.READY)

        await handler.handle(QueueFileCommand(tracked_file=tf))
        queue.put.assert_not_awaited()

    async def test_queue_not_initialized(self, deps):
        handler, state_machine, _, _, _ = deps
        handler._job_queue_service.get_queue.return_value = None
        tf = _make_tracked(status=FileStatus.READY)

        await handler.handle(QueueFileCommand(tracked_file=tf))
        # transition to IN_QUEUE happens before queue check
        state_machine.transition.assert_called_once()

    async def test_growing_file_detected(self, deps):
        handler, state_machine, _, queue, copy_strategy = deps
        copy_strategy._is_file_currently_growing.return_value = True
        tf = _make_tracked(status=FileStatus.READY)

        await handler.handle(QueueFileCommand(tracked_file=tf))

        # Verify the job was created with is_growing_at_queue_time=True
        job_arg = queue.put.call_args[0][0]
        assert job_arg.is_growing_at_queue_time is True


# ── ProcessJobCommandHandler ─────────────────────────────────────────


class TestProcessJobCommandHandler:

    @pytest.fixture
    def deps(self):
        space_manager = AsyncMock()
        space_manager.should_check_space = MagicMock(return_value=False)

        file_preparation_service = AsyncMock()
        prepared = MagicMock()
        prepared.job = _make_job()
        file_preparation_service.prepare_file_for_copy.return_value = prepared

        copy_executor = AsyncMock()
        finalization_service = AsyncMock()
        job_queue_service = AsyncMock()

        handler = ProcessJobCommandHandler(
            space_manager=space_manager,
            file_preparation_service=file_preparation_service,
            copy_executor=copy_executor,
            finalization_service=finalization_service,
            job_queue_service=job_queue_service,
        )
        return (
            handler, space_manager, file_preparation_service,
            copy_executor, finalization_service, job_queue_service, prepared,
        )

    async def test_successful_processing(self, deps):
        handler, _, _, copy_executor, finalization, job_queue, prepared = deps
        job = _make_job()

        await handler.handle(ProcessJobCommand(job=job))

        copy_executor.initialize_copy_status.assert_awaited_once_with(prepared)
        copy_executor.execute_copy.assert_awaited_once_with(prepared)
        finalization.finalize_success.assert_awaited_once()
        job_queue.mark_job_completed.assert_awaited_once_with(job)

    async def test_space_shortage_handled(self, deps):
        handler, space_manager, _, copy_executor, _, _, _ = deps
        space_manager.should_check_space.return_value = True
        space_check = MagicMock()
        space_check.has_space = False
        space_manager.check_space_for_job.return_value = space_check

        job = _make_job()
        await handler.handle(ProcessJobCommand(job=job))

        space_manager.handle_space_shortage.assert_awaited_once()
        copy_executor.execute_copy.assert_not_awaited()

    async def test_space_ok_continues(self, deps):
        handler, space_manager, _, copy_executor, _, _, _ = deps
        space_manager.should_check_space.return_value = True
        space_check = MagicMock()
        space_check.has_space = True
        space_manager.check_space_for_job.return_value = space_check

        job = _make_job()
        await handler.handle(ProcessJobCommand(job=job))

        copy_executor.execute_copy.assert_awaited_once()

    async def test_file_not_found_finalized_as_failure(self, deps):
        handler, _, file_prep, copy_executor, finalization, _, _ = deps
        file_prep.prepare_file_for_copy.return_value = None

        job = _make_job()
        await handler.handle(ProcessJobCommand(job=job))

        finalization.finalize_failure.assert_awaited_once()
        copy_executor.execute_copy.assert_not_awaited()

    async def test_copy_error_handled(self, deps):
        handler, _, _, copy_executor, finalization, job_queue, prepared = deps
        copy_executor.execute_copy.side_effect = Exception("disk error")

        job = _make_job()
        await handler.handle(ProcessJobCommand(job=job))

        copy_executor.handle_copy_failure.assert_awaited_once()
        finalization.finalize_success.assert_not_awaited()
        job_queue.mark_job_completed.assert_not_awaited()

    async def test_unexpected_error_finalized(self, deps):
        handler, _, file_prep, _, finalization, _, _ = deps
        file_prep.prepare_file_for_copy.side_effect = RuntimeError("unexpected")

        job = _make_job()
        await handler.handle(ProcessJobCommand(job=job))

        finalization.finalize_failure.assert_awaited_once()
