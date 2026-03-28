"""
Tests for JobCopyExecutor — executes copy operations with status management and error handling.
Tests initialization, copy execution, and error classification routing.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime
from pathlib import Path

from app.domains.file_processing.consumer.job_copy_executor import JobCopyExecutor
from app.domains.file_processing.consumer.job_models import QueueJob, PreparedFile
from app.domains.file_processing.copy.exceptions import FileCopyError
from app.domains.file_processing.copy.network_error_detector import NetworkError
from app.core.exceptions import InvalidTransitionError
from app.core.events.file_events import FileCopyStartedEvent, FileCopyFailedEvent
from app.models import TrackedFile, FileStatus


def _make_job(file_id: str = "test-id") -> QueueJob:
    return QueueJob(
        file_id=file_id,
        file_path="/test/source.mxf",
        file_size=5000,
        creation_time=datetime.now(),
        is_growing_at_queue_time=False,
        added_to_queue_at=datetime.now(),
    )


def _make_prepared(file_id: str = "test-id", status: FileStatus = FileStatus.COPYING) -> PreparedFile:
    return PreparedFile(
        job=_make_job(file_id),
        strategy_name="GrowingCopy",
        initial_status=status,
        destination_path=Path("/dest/source.mxf"),
    )


def _make_tracked(file_id: str = "test-id") -> TrackedFile:
    return TrackedFile(
        id=file_id,
        file_path="/test/source.mxf",
        file_size=5000,
        status=FileStatus.IN_QUEUE,
    )


def _make_executor():
    settings = MagicMock()
    repo = MagicMock()
    repo.get_by_id = AsyncMock()
    copy_strategy = MagicMock()
    copy_strategy.copy_file = AsyncMock(return_value=True)
    state_machine = MagicMock()
    state_machine.transition = AsyncMock()
    event_bus = MagicMock()
    event_bus.publish = AsyncMock()
    error_classifier = MagicMock()

    executor = JobCopyExecutor(
        settings=settings,
        file_repository=repo,
        copy_strategy=copy_strategy,
        state_machine=state_machine,
        error_classifier=error_classifier,
        event_bus=event_bus,
    )
    return executor, repo, copy_strategy, state_machine, event_bus, error_classifier


class TestInitializeCopyStatus:

    @pytest.mark.asyncio
    async def test_transitions_to_initial_status(self):
        ex, _, _, sm, eb, _ = _make_executor()
        prepared = _make_prepared(status=FileStatus.COPYING)

        await ex.initialize_copy_status(prepared)

        sm.transition.assert_awaited_once()
        call_kwargs = sm.transition.call_args[1]
        assert call_kwargs["file_id"] == "test-id"
        assert call_kwargs["new_status"] == FileStatus.COPYING

    @pytest.mark.asyncio
    async def test_publishes_copy_started_event(self):
        ex, _, _, sm, eb, _ = _make_executor()
        prepared = _make_prepared()

        await ex.initialize_copy_status(prepared)

        eb.publish.assert_awaited_once()
        event = eb.publish.call_args[0][0]
        assert isinstance(event, FileCopyStartedEvent)
        assert event.file_id == "test-id"

    @pytest.mark.asyncio
    async def test_handles_invalid_transition_gracefully(self):
        ex, _, _, sm, eb, _ = _make_executor()
        sm.transition.side_effect = InvalidTransitionError("/test/file.mxf", "Ready", "Copying")

        await ex.initialize_copy_status(_make_prepared())
        # Should not raise — logged as warning
        eb.publish.assert_not_awaited()


class TestExecuteCopy:

    @pytest.mark.asyncio
    async def test_successful_copy(self):
        ex, repo, strategy, _, _, _ = _make_executor()
        repo.get_by_id.return_value = _make_tracked()
        strategy.copy_file.return_value = True

        result = await ex.execute_copy(_make_prepared())

        assert result is True
        strategy.copy_file.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_failed_copy(self):
        ex, repo, strategy, _, _, _ = _make_executor()
        repo.get_by_id.return_value = _make_tracked()
        strategy.copy_file.return_value = False

        result = await ex.execute_copy(_make_prepared())

        assert result is False

    @pytest.mark.asyncio
    async def test_file_not_found_bubbles_up(self):
        ex, repo, strategy, _, _, _ = _make_executor()
        repo.get_by_id.return_value = _make_tracked()
        strategy.copy_file.side_effect = FileNotFoundError("gone")

        with pytest.raises(FileNotFoundError):
            await ex.execute_copy(_make_prepared())

    @pytest.mark.asyncio
    async def test_network_error_bubbles_up(self):
        ex, repo, strategy, _, _, _ = _make_executor()
        repo.get_by_id.return_value = _make_tracked()
        strategy.copy_file.side_effect = NetworkError("network down")

        with pytest.raises(NetworkError):
            await ex.execute_copy(_make_prepared())

    @pytest.mark.asyncio
    async def test_unexpected_error_wrapped_as_file_copy_error(self):
        ex, repo, strategy, _, _, _ = _make_executor()
        repo.get_by_id.return_value = _make_tracked()
        strategy.copy_file.side_effect = OSError("disk error")

        with pytest.raises(FileCopyError, match="Unexpected error"):
            await ex.execute_copy(_make_prepared())

    @pytest.mark.asyncio
    async def test_tracked_file_not_found_returns_false(self):
        ex, repo, strategy, _, _, _ = _make_executor()
        repo.get_by_id.return_value = None

        result = await ex.execute_copy(_make_prepared())

        assert result is False
        strategy.copy_file.assert_not_awaited()


class TestHandleCopyFailure:

    @pytest.mark.asyncio
    async def test_classified_as_removed(self):
        ex, _, _, sm, eb, classifier = _make_executor()
        classifier.classify_copy_error.return_value = (FileStatus.REMOVED, "source gone")

        result = await ex.handle_copy_failure(_make_prepared(), FileNotFoundError("gone"))

        assert result is False
        sm.transition.assert_awaited_once()
        call_kwargs = sm.transition.call_args[1]
        assert call_kwargs["new_status"] == FileStatus.REMOVED

    @pytest.mark.asyncio
    async def test_classified_as_failed(self):
        ex, _, _, sm, eb, classifier = _make_executor()
        classifier.classify_copy_error.return_value = (FileStatus.FAILED, "disk error")

        result = await ex.handle_copy_failure(_make_prepared(), OSError("disk"))

        assert result is False
        sm.transition.assert_awaited_once()
        call_kwargs = sm.transition.call_args[1]
        assert call_kwargs["new_status"] == FileStatus.FAILED

    @pytest.mark.asyncio
    async def test_no_classifier_defaults_to_failed(self):
        ex, _, _, sm, eb, _ = _make_executor()
        ex.error_classifier = None

        result = await ex.handle_copy_failure(_make_prepared(), RuntimeError("boom"))

        assert result is False
        sm.transition.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_failure_publishes_copy_failed_event(self):
        ex, _, _, sm, eb, classifier = _make_executor()
        classifier.classify_copy_error.return_value = (FileStatus.FAILED, "bad disk")

        await ex.handle_copy_failure(_make_prepared(), OSError("disk"))

        # Event bus should be called for the failure event
        eb.publish.assert_awaited()
        event = eb.publish.call_args[0][0]
        assert isinstance(event, FileCopyFailedEvent)

    @pytest.mark.asyncio
    async def test_invalid_transition_in_failure_handler_is_caught(self):
        ex, _, _, sm, eb, classifier = _make_executor()
        classifier.classify_copy_error.return_value = (FileStatus.FAILED, "err")
        sm.transition.side_effect = InvalidTransitionError("/test.mxf", "Ready", "Failed")

        # Should not raise
        result = await ex.handle_copy_failure(_make_prepared(), RuntimeError("boom"))
        assert result is False


class TestInfo:

    def test_get_copy_executor_info(self):
        ex, _, _, _, _, _ = _make_executor()
        info = ex.get_copy_executor_info()
        assert "copy_strategy" in info
        assert info["file_repository_available"] is True
