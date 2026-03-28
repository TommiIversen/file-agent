"""
Tests for JobSpaceManager — space checking and shortage workflows.
Tests the branching logic: enough space, network issue, space shortage, and fallback.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from app.domains.file_processing.consumer.job_space_manager import JobSpaceManager
from app.domains.file_processing.consumer.job_models import QueueJob
from app.models import FileStatus, SpaceCheckResult


def _make_job(file_id: str = "test-id", file_size: int = 5000) -> QueueJob:
    return QueueJob(
        file_id=file_id,
        file_path="/test/file.mxf",
        file_size=file_size,
        creation_time=datetime.now(),
        is_growing_at_queue_time=False,
        added_to_queue_at=datetime.now(),
    )


def _make_space_result(
    has_space: bool = True,
    reason: str = "OK",
    available_bytes: int = 100_000_000,
    required_bytes: int = 50_000_000,
    file_size_bytes: int = 40_000_000,
) -> SpaceCheckResult:
    return SpaceCheckResult(
        has_space=has_space,
        available_bytes=available_bytes,
        required_bytes=required_bytes,
        file_size_bytes=file_size_bytes,
        safety_margin_bytes=10_000_000,
        reason=reason,
    )


def _make_tracked(file_id: str = "test-id") -> MagicMock:
    from app.models import TrackedFile
    return TrackedFile(
        id=file_id,
        file_path="/test/file.mxf",
        file_size=5000,
        status=FileStatus.IN_QUEUE,
    )


def _make_manager():
    settings = MagicMock()
    settings.enable_pre_copy_space_check = True
    repo = MagicMock()
    repo.get_by_id = AsyncMock()
    space_checker = MagicMock()
    state_machine = MagicMock()
    state_machine.transition = AsyncMock()
    retry_manager = MagicMock()
    retry_manager.schedule_space_retry = AsyncMock()
    event_bus = MagicMock()
    event_bus.publish = AsyncMock()

    mgr = JobSpaceManager(settings, repo, space_checker, state_machine, retry_manager, event_bus)
    return mgr, repo, space_checker, state_machine, retry_manager


class TestShouldCheckSpace:

    def test_enabled_with_checker(self):
        mgr, _, _, _, _ = _make_manager()
        assert mgr.should_check_space() is True

    def test_disabled_by_settings(self):
        mgr, _, _, _, _ = _make_manager()
        mgr.settings.enable_pre_copy_space_check = False
        assert mgr.should_check_space() is False

    def test_disabled_when_no_checker(self):
        mgr, _, _, _, _ = _make_manager()
        mgr.space_checker = None
        assert mgr.should_check_space() is False


class TestCheckSpaceForJob:

    @pytest.mark.asyncio
    async def test_delegates_to_space_checker(self):
        mgr, _, checker, _, _ = _make_manager()
        expected = _make_space_result(has_space=True)
        checker.check_space_for_file.return_value = expected

        result = await mgr.check_space_for_job(_make_job(file_size=5000))

        checker.check_space_for_file.assert_called_once_with(5000)
        assert result.has_space is True

    @pytest.mark.asyncio
    async def test_no_checker_returns_has_space(self):
        mgr, _, _, _, _ = _make_manager()
        mgr.space_checker = None

        result = await mgr.check_space_for_job(_make_job(file_size=1000))

        assert result.has_space is True
        assert result.reason == "No space checker configured"


class TestHandleSpaceShortageNetwork:

    @pytest.mark.asyncio
    async def test_network_issue_transitions_to_waiting_for_network(self):
        mgr, repo, _, sm, _ = _make_manager()
        repo.get_by_id.return_value = _make_tracked()
        space_check = _make_space_result(has_space=False, reason="Destination not accessible: mount failed")

        result = await mgr.handle_space_shortage(_make_job(), space_check)

        assert result.success is False
        assert result.should_retry is True
        sm.transition.assert_awaited_once()
        call_kwargs = sm.transition.call_args[1]
        assert call_kwargs["new_status"] == FileStatus.WAITING_FOR_NETWORK


class TestHandleSpaceShortageActual:

    @pytest.mark.asyncio
    async def test_space_shortage_schedules_retry(self):
        mgr, repo, _, sm, retry_mgr = _make_manager()
        tracked = _make_tracked()
        repo.get_by_id.return_value = tracked
        space_check = _make_space_result(has_space=False, reason="Insufficient space: 3GB available, 8GB required")

        result = await mgr.handle_space_shortage(_make_job(), space_check)

        assert result.success is False
        assert result.retry_scheduled is True
        assert result.space_shortage is True
        retry_mgr.schedule_space_retry.assert_awaited_once_with(tracked, space_check)

    @pytest.mark.asyncio
    async def test_space_shortage_no_retry_manager_falls_through_to_failed(self):
        mgr, repo, _, sm, _ = _make_manager()
        mgr.retry_manager = None
        repo.get_by_id.return_value = _make_tracked()
        space_check = _make_space_result(has_space=False, reason="Insufficient space")

        result = await mgr.handle_space_shortage(_make_job(), space_check)

        assert result.success is False
        assert result.space_shortage is True
        sm.transition.assert_awaited_once()
        call_kwargs = sm.transition.call_args[1]
        assert call_kwargs["new_status"] == FileStatus.FAILED

    @pytest.mark.asyncio
    async def test_retry_manager_error_falls_through_to_failed(self):
        mgr, repo, _, sm, retry_mgr = _make_manager()
        repo.get_by_id.return_value = _make_tracked()
        retry_mgr.schedule_space_retry.side_effect = RuntimeError("retry broke")
        space_check = _make_space_result(has_space=False, reason="Insufficient space")

        result = await mgr.handle_space_shortage(_make_job(), space_check)

        assert result.success is False
        assert result.space_shortage is True
        # Should fall through and transition to FAILED
        sm.transition.assert_awaited_once()


class TestHandleSpaceShortageEdgeCases:

    @pytest.mark.asyncio
    async def test_tracked_file_not_found(self):
        mgr, repo, _, _, _ = _make_manager()
        repo.get_by_id.return_value = None

        result = await mgr.handle_space_shortage(
            _make_job(),
            _make_space_result(has_space=False, reason="Insufficient space"),
        )

        assert result.success is False
        assert "not found" in result.error_message


class TestSpaceManagerInfo:

    def test_get_space_manager_info(self):
        mgr, _, _, _, _ = _make_manager()
        info = mgr.get_space_manager_info()

        assert info["space_checking_enabled"] is True
        assert info["space_checker_available"] is True
        assert info["space_retry_manager_available"] is True
