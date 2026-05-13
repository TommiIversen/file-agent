"""
Recording Session Tracker

Tracks recording sessions across Justin channels.
A session starts when the first channel begins recording and ends
when all channels have stopped (after a configurable grace period).

All files discovered during or shortly after a session share the same
canonical session_time, ensuring they land in the same output folder.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RecordingSession:
    """Represents a single recording session spanning multiple channels."""

    session_id: str
    session_time: str  # "HHMMSS" formatted from started_at
    started_at: datetime
    ended_at: Optional[datetime] = None
    channel_names: set[str] = field(default_factory=set)

    @property
    def is_active(self) -> bool:
        return self.ended_at is None


class RecordingSessionTracker:
    """
    Tracks the lifecycle of recording sessions.

    A session is created when the first channel starts recording.
    It ends when ALL channels have stopped AND the grace period has elapsed.
    The grace period prevents accidental session splits from quick restart cycles.
    """

    def __init__(
        self,
        grace_period_seconds: float = 5.0,
        history_minutes: int = 120,
    ) -> None:
        self._grace_period_seconds = grace_period_seconds
        self._history_minutes = history_minutes
        self._active_session: Optional[RecordingSession] = None
        self._recent_sessions: list[RecordingSession] = []
        self._grace_period_task: Optional[asyncio.Task[None]] = None

    @property
    def active_session(self) -> Optional[RecordingSession]:
        return self._active_session

    @property
    def recent_sessions(self) -> list[RecordingSession]:
        return list(self._recent_sessions)

    def handle_channel_started(self, channel_name: str) -> None:
        """
        Handle a channel starting recording.

        If no active session exists, a new session is created.
        If the grace period timer is running (all channels were stopped briefly),
        the timer is cancelled and the existing session continues.
        """
        # Cancel grace period if running (quick restart scenario)
        if self._grace_period_task is not None and not self._grace_period_task.done():
            self._grace_period_task.cancel()
            self._grace_period_task = None
            logger.info(
                "Grace period cancelled — session %s continues (channel %s restarted)",
                self._active_session.session_id[:8] if self._active_session else "?",
                channel_name,
            )

        if self._active_session is None:
            # Create new session
            now = datetime.now(timezone.utc)
            session_time = now.strftime("%H%M%S")
            self._active_session = RecordingSession(
                session_id=str(uuid.uuid4()),
                session_time=session_time,
                started_at=now,
                channel_names={channel_name},
            )
            logger.info(
                "Recording session started: id=%s, session_time=%s, first_channel=%s",
                self._active_session.session_id[:8],
                session_time,
                channel_name,
            )
        else:
            # Add channel to existing session
            self._active_session.channel_names.add(channel_name)
            logger.debug(
                "Channel %s joined session %s (channels: %d)",
                channel_name,
                self._active_session.session_id[:8],
                len(self._active_session.channel_names),
            )

    def handle_channel_stopped(
        self, channel_name: str, active_recording_channels: set[str]
    ) -> None:
        """
        Handle a channel stopping recording.

        When all channels have stopped, a grace period timer starts.
        If no channel restarts before the grace period elapses, the session ends.
        """
        if self._active_session is None:
            return

        if not active_recording_channels:
            # All channels stopped — start grace period
            logger.info(
                "All channels stopped in session %s — grace period %.1fs started",
                self._active_session.session_id[:8],
                self._grace_period_seconds,
            )
            self._grace_period_task = asyncio.create_task(
                self._end_session_after_grace_period()
            )

    async def _end_session_after_grace_period(self) -> None:
        """Wait for grace period, then finalize the active session."""
        try:
            await asyncio.sleep(self._grace_period_seconds)
        except asyncio.CancelledError:
            return  # Grace period cancelled (channel restarted)

        if self._active_session is not None:
            self._active_session.ended_at = datetime.now(timezone.utc)
            self._recent_sessions.append(self._active_session)
            logger.info(
                "Recording session ended: id=%s, session_time=%s, channels=%s",
                self._active_session.session_id[:8],
                self._active_session.session_time,
                sorted(self._active_session.channel_names),
            )
            self._active_session = None
            self._prune_old_sessions()

        self._grace_period_task = None

    def _prune_old_sessions(self) -> None:
        """Remove sessions older than history_minutes."""
        if not self._recent_sessions:
            return
        cutoff = datetime.now(timezone.utc).timestamp() - (
            self._history_minutes * 60
        )
        self._recent_sessions = [
            s
            for s in self._recent_sessions
            if s.started_at.timestamp() > cutoff
        ]

    def get_session_time(
        self, file_creation_time: Optional[datetime] = None
    ) -> Optional[str]:
        """
        Get the canonical session_time for a file.

        1. If there is an active session → return its session_time.
        2. If file_creation_time is provided → search recent sessions
           where the file was created during (or shortly after) the session.
        3. Otherwise → return None (no session info available).
        """
        # Active session takes priority
        if self._active_session is not None:
            return self._active_session.session_time

        # Search recent sessions by file creation time
        if file_creation_time is not None:
            creation_ts = file_creation_time.timestamp()
            # Allow a 60-second margin after session end for late-arriving files
            margin_seconds = 60.0

            for session in reversed(self._recent_sessions):
                start_ts = session.started_at.timestamp()
                end_ts = (
                    session.ended_at.timestamp() + margin_seconds
                    if session.ended_at
                    else start_ts + margin_seconds
                )
                if start_ts <= creation_ts <= end_ts:
                    logger.debug(
                        "File (created %s) matched recent session %s (time=%s)",
                        file_creation_time,
                        session.session_id[:8],
                        session.session_time,
                    )
                    return session.session_time

        return None
