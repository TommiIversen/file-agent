"""Tests for RecordingSessionTracker."""
import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from app.domains.ingest_monitor.session_tracker import (
    RecordingSession,
    RecordingSessionTracker,
)


class TestRecordingSession:
    """Tests for RecordingSession dataclass."""

    def test_is_active_when_no_ended_at(self) -> None:
        session = RecordingSession(
            session_id="test",
            session_time="120530",
            started_at=datetime.now(timezone.utc),
        )
        assert session.is_active is True

    def test_is_not_active_when_ended(self) -> None:
        session = RecordingSession(
            session_id="test",
            session_time="120530",
            started_at=datetime.now(timezone.utc),
            ended_at=datetime.now(timezone.utc),
        )
        assert session.is_active is False


class TestRecordingSessionTracker:
    """Tests for RecordingSessionTracker."""

    def _make_tracker(
        self, grace_period: float = 0.1, history_minutes: int = 120
    ) -> RecordingSessionTracker:
        return RecordingSessionTracker(
            grace_period_seconds=grace_period,
            history_minutes=history_minutes,
        )

    def test_first_channel_creates_session(self) -> None:
        tracker = self._make_tracker()
        tracker.handle_channel_started("KAM_1")
        assert tracker.active_session is not None
        assert "KAM_1" in tracker.active_session.channel_names

    def test_second_channel_joins_existing_session(self) -> None:
        tracker = self._make_tracker()
        tracker.handle_channel_started("KAM_1")
        tracker.handle_channel_started("KAM_2")
        assert tracker.active_session is not None
        assert len(tracker.active_session.channel_names) == 2

    def test_all_channels_same_session_time(self) -> None:
        tracker = self._make_tracker()
        tracker.handle_channel_started("KAM_1")
        assert tracker.active_session is not None
        session_time = tracker.active_session.session_time
        tracker.handle_channel_started("KAM_2")
        tracker.handle_channel_started("KAM_3")
        assert tracker.active_session is not None
        assert tracker.active_session.session_time == session_time

    @pytest.mark.asyncio
    async def test_session_ends_after_grace_period(self) -> None:
        tracker = self._make_tracker(grace_period=0.05)
        tracker.handle_channel_started("KAM_1")
        tracker.handle_channel_stopped("KAM_1", active_recording_channels=set())
        # Wait for grace period to elapse
        await asyncio.sleep(0.15)
        assert tracker.active_session is None
        assert len(tracker.recent_sessions) == 1

    @pytest.mark.asyncio
    async def test_quick_restart_cancels_grace_period(self) -> None:
        tracker = self._make_tracker(grace_period=1.0)
        tracker.handle_channel_started("KAM_1")
        assert tracker.active_session is not None
        session_id = tracker.active_session.session_id
        # Stop all channels
        tracker.handle_channel_stopped("KAM_1", active_recording_channels=set())
        # Restart quickly (before grace period)
        tracker.handle_channel_started("KAM_2")
        assert tracker.active_session is not None
        assert tracker.active_session.session_id == session_id  # Same session!

    def test_get_session_time_active(self) -> None:
        tracker = self._make_tracker()
        tracker.handle_channel_started("KAM_1")
        result = tracker.get_session_time()
        assert result is not None
        assert len(result) == 6  # "HHMMSS"

    def test_get_session_time_no_session(self) -> None:
        tracker = self._make_tracker()
        result = tracker.get_session_time()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_session_time_by_creation_time(self) -> None:
        tracker = self._make_tracker(grace_period=0.05)
        tracker.handle_channel_started("KAM_1")
        assert tracker.active_session is not None
        session_time = tracker.active_session.session_time
        started_at = tracker.active_session.started_at
        tracker.handle_channel_stopped("KAM_1", active_recording_channels=set())
        await asyncio.sleep(0.15)  # Let session end
        assert tracker.active_session is None

        # File created during the session should match
        file_time = started_at + timedelta(seconds=5)
        result = tracker.get_session_time(file_creation_time=file_time)
        assert result == session_time

    @pytest.mark.asyncio
    async def test_get_session_time_no_match_old_file(self) -> None:
        tracker = self._make_tracker(grace_period=0.05)
        tracker.handle_channel_started("KAM_1")
        tracker.handle_channel_stopped("KAM_1", active_recording_channels=set())
        await asyncio.sleep(0.15)

        # File created way before session → no match
        old_time = datetime(2020, 1, 1, tzinfo=timezone.utc)
        result = tracker.get_session_time(file_creation_time=old_time)
        assert result is None

    def test_not_all_channels_stopped(self) -> None:
        """Session should NOT end when only some channels stop."""
        tracker = self._make_tracker()
        tracker.handle_channel_started("KAM_1")
        tracker.handle_channel_started("KAM_2")
        tracker.handle_channel_stopped("KAM_1", active_recording_channels={"KAM_2"})
        # Grace period should NOT have started
        assert tracker._grace_period_task is None
        assert tracker.active_session is not None

    def test_handle_channel_stopped_no_active_session(self) -> None:
        """Stopping a channel with no active session should be a no-op."""
        tracker = self._make_tracker()
        tracker.handle_channel_stopped("KAM_1", active_recording_channels=set())
        assert tracker.active_session is None

    @pytest.mark.asyncio
    async def test_session_history_pruning(self) -> None:
        """Old sessions should be pruned after history_minutes."""
        tracker = self._make_tracker(grace_period=0.05, history_minutes=0)
        tracker.handle_channel_started("KAM_1")
        tracker.handle_channel_stopped("KAM_1", active_recording_channels=set())
        await asyncio.sleep(0.15)
        # With 0 minutes history, session should be pruned immediately
        assert len(tracker.recent_sessions) == 0
