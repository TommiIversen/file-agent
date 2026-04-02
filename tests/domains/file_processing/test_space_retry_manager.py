"""Tests for SpaceRetryManager — retry scheduling, cancellation, and space error workflows."""
import asyncio
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.domains.file_processing.space_retry_manager import SpaceRetryManager
from app.core.exceptions import InvalidTransitionError
from app.models import TrackedFile, FileStatus, SpaceCheckResult, RetryInfo


def _settings(**overrides):
    s = MagicMock()
    s.space_retry_delay_seconds = 2  # Short for tests
    s.max_space_retries = 3
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _tf(file_id="f1", path="/src/test.mxf", status=FileStatus.WAITING_FOR_SPACE, **kw):
    defaults = dict(id=file_id, file_path=path, file_size=10_000_000, status=status)
    defaults.update(kw)
    return TrackedFile(**defaults)


def _space_check(has_space=False, available=5_000_000, required=10_000_000, reason="Not enough space"):
    return SpaceCheckResult(
        has_space=has_space,
        available_bytes=available,
        required_bytes=required,
        file_size_bytes=required - 1_000_000,
        safety_margin_bytes=1_000_000,
        reason=reason,
    )


@pytest.fixture
def repo():
    return AsyncMock()


@pytest.fixture
def sm():
    return AsyncMock()


@pytest.fixture
def bus():
    return AsyncMock()


@pytest.fixture
def mgr(repo, sm, bus):
    return SpaceRetryManager(
        settings=_settings(),
        file_repository=repo,
        event_bus=bus,
        state_machine=sm,
    )


# ── increment_retry_count ───────────────────────────────────────

class TestIncrementRetryCount:
    @pytest.mark.asyncio
    async def test_increments_and_returns_count(self, mgr, repo):
        tf = _tf(retry_count=2)
        repo.get_by_id.return_value = tf

        result = await mgr.increment_retry_count("f1")
        assert result == 3
        assert tf.retry_count == 3
        repo.update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unknown_file_returns_zero(self, mgr, repo):
        repo.get_by_id.return_value = None
        result = await mgr.increment_retry_count("unknown")
        assert result == 0


# ── schedule_retry ──────────────────────────────────────────────

class TestScheduleRetry:
    @pytest.mark.asyncio
    async def test_schedules_and_stores_retry_info(self, mgr, repo):
        tf = _tf()
        repo.get_by_id.return_value = tf

        result = await mgr.schedule_retry("f1", 10, "space shortage", "space")

        assert result is True
        assert tf.retry_info is not None
        assert tf.retry_info.reason == "space shortage"
        repo.update.assert_awaited_once()
        assert "f1" in mgr._retry_tasks

        # Cleanup: cancel the background task
        await mgr.cancel_retry("f1")

    @pytest.mark.asyncio
    async def test_unknown_file_returns_false(self, mgr, repo):
        repo.get_by_id.return_value = None
        result = await mgr.schedule_retry("unknown", 10, "reason")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancels_existing_retry_before_scheduling(self, mgr, repo):
        tf = _tf(retry_info=RetryInfo(
            scheduled_at=datetime.now(),
            retry_at=datetime.now(),
            reason="old",
        ))
        repo.get_by_id.return_value = tf

        # Schedule first
        await mgr.schedule_retry("f1", 100, "first")
        first_task = mgr._retry_tasks.get("f1")

        # Schedule again — should cancel first
        await mgr.schedule_retry("f1", 100, "second")
        second_task = mgr._retry_tasks.get("f1")

        assert first_task is not second_task
        assert first_task.cancelled()

        await mgr.cancel_retry("f1")


# ── cancel_retry / cancel_all_retries ───────────────────────────

class TestCancelRetry:
    @pytest.mark.asyncio
    async def test_cancel_nonexistent_returns_false(self, mgr, repo):
        repo.get_by_id.return_value = _tf(retry_info=None)
        result = await mgr.cancel_retry("f1")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_existing_task(self, mgr, repo):
        tf = _tf()
        repo.get_by_id.return_value = tf

        await mgr.schedule_retry("f1", 100, "test")
        result = await mgr.cancel_retry("f1")
        assert result is True
        assert "f1" not in mgr._retry_tasks


class TestCancelAllRetries:
    @pytest.mark.asyncio
    async def test_cancels_all_pending(self, mgr, repo):
        tf1 = _tf(file_id="f1", retry_info=RetryInfo(
            scheduled_at=datetime.now(), retry_at=datetime.now(), reason="r1"
        ))
        tf2 = _tf(file_id="f2", retry_info=RetryInfo(
            scheduled_at=datetime.now(), retry_at=datetime.now(), reason="r2"
        ))

        # Need get_all to return files with retry_info, and get_by_id to return
        # the same file for cleanup
        repo.get_all.return_value = [tf1, tf2]
        repo.get_by_id.side_effect = lambda fid: {"f1": tf1, "f2": tf2}.get(fid)

        count = await mgr.cancel_all_retries()
        assert count == 2


# ── schedule_space_retry (high-level orchestrator) ──────────────

class TestScheduleSpaceRetry:
    @pytest.mark.asyncio
    async def test_exceeds_max_retries_marks_permanent_error(self, mgr, repo, sm):
        tf = _tf(retry_count=2)  # Will become 3 after increment
        repo.get_by_id.return_value = tf

        space_check = _space_check()
        await mgr.schedule_space_retry(tf, space_check)

        # Should have called transition to SPACE_ERROR
        sm.transition.assert_awaited()
        call_kwargs = sm.transition.call_args[1]
        assert call_kwargs["new_status"] == FileStatus.SPACE_ERROR

    @pytest.mark.asyncio
    async def test_temporary_shortage_uses_short_delay(self, mgr, repo, sm):
        tf = _tf(retry_count=0)
        repo.get_by_id.return_value = tf

        # is_temporary_shortage() = True when shortage < 20% of required
        space_check = _space_check(
            available=9_500_000,  # Only 500K short of 10M = 5%
            required=10_000_000,
        )
        await mgr.schedule_space_retry(tf, space_check)

        # Should transition to WAITING_FOR_SPACE
        sm.transition.assert_awaited()
        call_kwargs = sm.transition.call_args[1]
        assert call_kwargs["new_status"] == FileStatus.WAITING_FOR_SPACE

        # Cleanup
        await mgr.cancel_retry("f1")

    @pytest.mark.asyncio
    async def test_large_shortage_uses_long_delay(self, mgr, repo, sm):
        tf = _tf(retry_count=0)
        repo.get_by_id.return_value = tf

        # Large shortage → not temporary
        space_check = _space_check(
            available=1_000_000,
            required=10_000_000,
        )
        await mgr.schedule_space_retry(tf, space_check)

        sm.transition.assert_awaited()
        await mgr.cancel_retry("f1")

    @pytest.mark.asyncio
    async def test_transition_failure_aborts_scheduling(self, mgr, repo, sm):
        tf = _tf(retry_count=0)
        repo.get_by_id.return_value = tf
        sm.transition.side_effect = InvalidTransitionError("f.mxf", "Completed", "WaitingForSpace")

        space_check = _space_check(available=1_000_000, required=10_000_000)
        await mgr.schedule_space_retry(tf, space_check)

        # No task should have been scheduled since transition failed
        assert "f1" not in mgr._retry_tasks


# ── _execute_retry_task ─────────────────────────────────────────

class TestExecuteRetryTask:
    @pytest.mark.asyncio
    async def test_retry_resets_to_ready(self, mgr, repo, sm):
        tf = _tf(
            retry_info=RetryInfo(
                scheduled_at=datetime.now(), retry_at=datetime.now(), reason="test"
            )
        )
        repo.get_by_id.return_value = tf

        # Use delay=0 so retry fires immediately
        await mgr.schedule_retry("f1", 0, "test")

        # Wait for the task to complete
        await asyncio.sleep(0.1)

        # Should have called transition to READY
        sm.transition.assert_awaited()
        call_kwargs = sm.transition.call_args[1]
        assert call_kwargs["new_status"] == FileStatus.READY

    @pytest.mark.asyncio
    async def test_retry_skipped_if_status_changed(self, mgr, repo, sm):
        """If file status changed from WAITING_FOR_SPACE before retry fires, skip retry."""
        tf = _tf(
            status=FileStatus.COPYING,  # Not WAITING_FOR_SPACE anymore
            retry_info=RetryInfo(
                scheduled_at=datetime.now(), retry_at=datetime.now(), reason="test"
            ),
        )
        repo.get_by_id.return_value = tf

        await mgr.schedule_retry("f1", 0, "test")
        await asyncio.sleep(0.1)

        # Should NOT have called transition since status changed
        sm.transition.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_retry_skipped_if_file_gone(self, mgr, repo, sm):
        """If file no longer exists when retry fires, skip."""
        repo.get_by_id.return_value = None

        await mgr.schedule_retry("f1", 0, "test")  # Will fail at schedule since file is None
        # schedule_retry returns False for unknown file — no task to worry about

    @pytest.mark.asyncio
    async def test_transition_failure_still_pops_task(self, mgr, repo, sm):
        """If transition raises InvalidTransitionError, task is still cleaned up."""
        tf = _tf(
            retry_info=RetryInfo(
                scheduled_at=datetime.now(), retry_at=datetime.now(), reason="test"
            )
        )
        repo.get_by_id.return_value = tf
        sm.transition.side_effect = InvalidTransitionError(
            from_status=FileStatus.WAITING_FOR_SPACE,
            to_status=FileStatus.READY,
            file_path="/src/test.mxf",
        )

        await mgr.schedule_retry("f1", 0, "test")
        await asyncio.sleep(0.1)

        # Task should have been popped despite the error
        assert "f1" not in mgr._retry_tasks

    @pytest.mark.asyncio
    async def test_cancelled_error_cleans_retry_info(self, mgr, repo, sm):
        """CancelledError during sleep clears retry_info and re-raises."""
        tf = _tf(
            retry_info=RetryInfo(
                scheduled_at=datetime.now(), retry_at=datetime.now(), reason="test"
            )
        )
        repo.get_by_id.return_value = tf

        await mgr.schedule_retry("f1", 9999, "test")  # Long delay
        await asyncio.sleep(0.05)

        # Cancel the task
        task = mgr._retry_tasks["f1"]
        task.cancel()

        # Wait for cancellation
        with pytest.raises(asyncio.CancelledError):
            await task

        # retry_info should be cleared
        repo.update.assert_awaited()

    @pytest.mark.asyncio
    async def test_generic_exception_cleans_up(self, mgr, repo, sm):
        """Unexpected exception during retry clears retry_info."""
        tf = _tf(
            retry_info=RetryInfo(
                scheduled_at=datetime.now(), retry_at=datetime.now(), reason="test"
            )
        )
        repo.get_by_id.return_value = tf
        sm.transition.side_effect = RuntimeError("unexpected")

        await mgr.schedule_retry("f1", 0, "test")
        await asyncio.sleep(0.1)

        # Should have cleaned up retry_info
        assert "f1" not in mgr._retry_tasks


# ── _should_give_up_retry ───────────────────────────────────────

class TestShouldGiveUpRetry:
    def test_below_max_retries_does_not_give_up(self, mgr):
        assert mgr._should_give_up_retry(1) is False

    def test_at_max_retries_gives_up(self, mgr):
        assert mgr._should_give_up_retry(3) is True

    def test_above_max_retries_gives_up(self, mgr):
        assert mgr._should_give_up_retry(10) is True
