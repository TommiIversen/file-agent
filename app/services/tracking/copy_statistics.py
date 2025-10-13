"""
Copy Statistics Tracker Strategy for File Transfer Agent.

Ekstrakteret fra FileCopyService som en del af SOLID principper implementering.
Håndterer tracking af copy statistikker, performance metrics og throughput calculations.

Strategy pattern gør statistik tracking modulært, testbart og udskifteligt.
"""

import logging
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from threading import Lock

from app.config import Settings


@dataclass
class CopySession:
    """
    Tracking data for en individual copy session.

    Bruges til at track performance metrics for individuelle filkopieringer.
    """

    file_path: str
    file_size: int
    started_at: datetime
    completed_at: Optional[datetime] = None
    bytes_transferred: int = 0
    retry_count: int = 0
    copy_strategy: str = ""

    @property
    def duration_seconds(self) -> float:
        """Get copy duration in seconds"""
        if self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return (datetime.now() - self.started_at).total_seconds()

    @property
    def transfer_rate_bytes_per_sec(self) -> float:
        """Get transfer rate in bytes per second"""
        duration = self.duration_seconds
        if duration > 0:
            return self.bytes_transferred / duration
        return 0.0

    @property
    def is_completed(self) -> bool:
        """Check if copy session is completed"""
        return self.completed_at is not None


@dataclass
class StatisticsSummary:
    """
    Comprehensive statistics summary for monitoring and reporting.

    Inkluderer både cumulative statistics og current performance metrics.
    """

    # Cumulative counters
    total_files_copied: int = 0
    total_files_failed: int = 0
    total_bytes_copied: int = 0

    # Session tracking
    active_sessions: int = 0
    completed_sessions: int = 0

    # Performance metrics
    average_transfer_rate_mbps: float = 0.0
    current_transfer_rate_mbps: float = 0.0
    peak_transfer_rate_mbps: float = 0.0

    # Timing information
    session_start_time: Optional[datetime] = None
    last_activity_time: Optional[datetime] = None
    uptime_seconds: float = 0.0

    # Derived properties
    @property
    def total_gb_copied(self) -> float:
        """Total gigabytes copied"""
        return round(self.total_bytes_copied / (1024**3), 2)

    @property
    def success_rate(self) -> float:
        """Success rate as percentage"""
        total_attempts = self.total_files_copied + self.total_files_failed
        if total_attempts > 0:
            return (self.total_files_copied / total_attempts) * 100.0
        return 0.0

    @property
    def average_file_size_mb(self) -> float:
        """Average file size in MB"""
        if self.total_files_copied > 0:
            return (self.total_bytes_copied / self.total_files_copied) / (1024**2)
        return 0.0


class CopyStatisticsTracker:
    """
    Strategy class for tracking copy statistics og performance metrics.

    Ansvar:
    1. Statistics Accumulation: Track totals for files, bytes, failures
    2. Performance Monitoring: Monitor transfer rates and throughput
    3. Session Tracking: Track individual copy sessions for analysis
    4. Report Generation: Provide detailed statistics for monitoring
    5. Reset Capabilities: Allow statistics reset for testing/maintenance

    Thread-safe implementation for concurrent access fra multiple consumers.
    """

    def __init__(self, settings: Settings, enable_session_tracking: bool = True):
        """
        Initialize CopyStatisticsTracker med konfiguration.

        Args:
            settings: Application settings
            enable_session_tracking: Whether to track individual sessions
        """
        self.settings = settings
        self.enable_session_tracking = enable_session_tracking

        # Thread safety
        self._lock = Lock()

        # Cumulative statistics
        self._total_files_copied = 0
        self._total_files_failed = 0
        self._total_bytes_copied = 0

        # Session tracking
        self._active_sessions: Dict[str, CopySession] = {}
        self._completed_sessions: List[CopySession] = []
        self._max_completed_sessions = 1000  # Limit memory usage

        # Performance tracking
        self._peak_transfer_rate = 0.0
        self._session_start_time = datetime.now()
        self._last_activity_time = datetime.now()

        # Rate calculation window (last 10 sessions for current rate)
        self._recent_sessions_window = 10

        logging.info("CopyStatisticsTracker initialiseret")
        logging.info(f"Session tracking enabled: {self.enable_session_tracking}")
        logging.info(f"Max completed sessions: {self._max_completed_sessions}")

    def start_copy_session(
        self, file_path: str, file_size: int, copy_strategy: str = ""
    ) -> None:
        """
        Start tracking af en ny copy session.

        Args:
            file_path: Path til fil der kopieres
            file_size: Størrelse af fil i bytes
            copy_strategy: Name of copy strategy being used
        """
        if not self.enable_session_tracking:
            return

        with self._lock:
            session = CopySession(
                file_path=file_path,
                file_size=file_size,
                started_at=datetime.now(),
                copy_strategy=copy_strategy,
            )

            self._active_sessions[file_path] = session
            self._last_activity_time = datetime.now()

            logging.debug(f"Started copy session: {file_path} ({file_size} bytes)")

    def update_session_progress(self, file_path: str, bytes_transferred: int) -> None:
        """
        Update progress for an active copy session.

        Args:
            file_path: Path til fil
            bytes_transferred: Antal bytes transferred så langt
        """
        if not self.enable_session_tracking:
            return

        with self._lock:
            session = self._active_sessions.get(file_path)
            if session:
                session.bytes_transferred = bytes_transferred
                self._last_activity_time = datetime.now()

    def complete_copy_session(
        self,
        file_path: str,
        success: bool,
        final_bytes_transferred: Optional[int] = None,
    ) -> None:
        """
        Complete en copy session og update cumulative statistics.

        Args:
            file_path: Path til fil
            success: Whether copy was successful
            final_bytes_transferred: Final amount of bytes transferred
        """
        with self._lock:
            # Update cumulative statistics
            if success:
                self._total_files_copied += 1
                # Always track bytes for successful copies
                if final_bytes_transferred is not None:
                    self._total_bytes_copied += final_bytes_transferred
            else:
                self._total_files_failed += 1

            self._last_activity_time = datetime.now()

            # Handle session tracking if enabled
            if self.enable_session_tracking:
                session = self._active_sessions.pop(file_path, None)
                if session:
                    session.completed_at = datetime.now()

                    if success and final_bytes_transferred is not None:
                        session.bytes_transferred = final_bytes_transferred

                        # Update peak transfer rate
                        rate = session.transfer_rate_bytes_per_sec
                        if rate > self._peak_transfer_rate:
                            self._peak_transfer_rate = rate

                    # Add to completed sessions with memory management
                    self._completed_sessions.append(session)
                    if len(self._completed_sessions) > self._max_completed_sessions:
                        # Remove oldest sessions to prevent memory leaks
                        self._completed_sessions = self._completed_sessions[
                            -self._max_completed_sessions :
                        ]

                    logging.debug(
                        f"Completed copy session: {file_path} (success: {success})"
                    )
                else:
                    # Session not found - this can happen if session tracking was started after the copy began
                    logging.debug(
                        f"Completed copy session without active session: {file_path} (success: {success})"
                    )

    def increment_retry_count(self, file_path: str) -> None:
        """
        Increment retry count for an active session.

        Args:
            file_path: Path til fil
        """
        if not self.enable_session_tracking:
            return

        with self._lock:
            session = self._active_sessions.get(file_path)
            if session:
                session.retry_count += 1

    def get_statistics_summary(self) -> StatisticsSummary:
        """
        Get comprehensive statistics summary.

        Returns:
            StatisticsSummary med alle current statistics
        """
        with self._lock:
            # Calculate current and average transfer rates
            current_rate_mbps = self._calculate_current_transfer_rate_mbps()
            average_rate_mbps = self._calculate_average_transfer_rate_mbps()
            peak_rate_mbps = self._peak_transfer_rate / (1024**2)  # Convert to Mbps

            # Calculate uptime
            uptime_seconds = (datetime.now() - self._session_start_time).total_seconds()

            return StatisticsSummary(
                total_files_copied=self._total_files_copied,
                total_files_failed=self._total_files_failed,
                total_bytes_copied=self._total_bytes_copied,
                active_sessions=len(self._active_sessions),
                completed_sessions=len(self._completed_sessions),
                average_transfer_rate_mbps=average_rate_mbps,
                current_transfer_rate_mbps=current_rate_mbps,
                peak_transfer_rate_mbps=peak_rate_mbps,
                session_start_time=self._session_start_time,
                last_activity_time=self._last_activity_time,
                uptime_seconds=uptime_seconds,
            )

    def get_detailed_statistics(self) -> Dict[str, Any]:
        """
        Get detailed statistics inklusive session information.

        Returns:
            Dictionary med detaljerede statistics
        """
        summary = self.get_statistics_summary()

        with self._lock:
            # Get active session details
            active_session_details = []
            for session in self._active_sessions.values():
                active_session_details.append(
                    {
                        "file_path": session.file_path,
                        "file_size": session.file_size,
                        "bytes_transferred": session.bytes_transferred,
                        "progress_percent": (
                            session.bytes_transferred / session.file_size * 100
                        )
                        if session.file_size > 0
                        else 0,
                        "duration_seconds": session.duration_seconds,
                        "transfer_rate_mbps": session.transfer_rate_bytes_per_sec
                        / (1024**2),
                        "retry_count": session.retry_count,
                        "copy_strategy": session.copy_strategy,
                    }
                )

            # Get recent completed session summary
            recent_sessions = (
                self._completed_sessions[-self._recent_sessions_window :]
                if self._completed_sessions
                else []
            )
            recent_session_summary = {
                "count": len(recent_sessions),
                "average_duration": sum(s.duration_seconds for s in recent_sessions)
                / len(recent_sessions)
                if recent_sessions
                else 0,
                "average_size_mb": sum(s.file_size for s in recent_sessions)
                / len(recent_sessions)
                / (1024**2)
                if recent_sessions
                else 0,
                "average_rate_mbps": sum(
                    s.transfer_rate_bytes_per_sec for s in recent_sessions
                )
                / len(recent_sessions)
                / (1024**2)
                if recent_sessions
                else 0,
            }

            return {
                # Summary statistics
                "summary": {
                    "total_files_copied": summary.total_files_copied,
                    "total_files_failed": summary.total_files_failed,
                    "total_bytes_copied": summary.total_bytes_copied,
                    "total_gb_copied": summary.total_gb_copied,
                    "success_rate": summary.success_rate,
                    "average_file_size_mb": summary.average_file_size_mb,
                },
                # Performance metrics
                "performance": {
                    "current_transfer_rate_mbps": summary.current_transfer_rate_mbps,
                    "average_transfer_rate_mbps": summary.average_transfer_rate_mbps,
                    "peak_transfer_rate_mbps": summary.peak_transfer_rate_mbps,
                    "uptime_seconds": summary.uptime_seconds,
                    "uptime_hours": summary.uptime_seconds / 3600,
                },
                # Session information
                "sessions": {
                    "active_count": summary.active_sessions,
                    "completed_count": summary.completed_sessions,
                    "active_details": active_session_details,
                    "recent_completed_summary": recent_session_summary,
                },
                # Timing information
                "timing": {
                    "session_start_time": summary.session_start_time.isoformat()
                    if summary.session_start_time
                    else None,
                    "last_activity_time": summary.last_activity_time.isoformat()
                    if summary.last_activity_time
                    else None,
                },
                # Configuration
                "config": {
                    "session_tracking_enabled": self.enable_session_tracking,
                    "max_completed_sessions": self._max_completed_sessions,
                    "recent_sessions_window": self._recent_sessions_window,
                },
            }

    def _calculate_current_transfer_rate_mbps(self) -> float:
        """Calculate current transfer rate based on recent sessions"""
        if not self._completed_sessions:
            return 0.0

        # Use last few completed sessions for current rate
        recent_sessions = self._completed_sessions[-self._recent_sessions_window :]
        if not recent_sessions:
            return 0.0

        # Calculate average rate of recent sessions
        total_rate = sum(
            session.transfer_rate_bytes_per_sec for session in recent_sessions
        )
        average_rate_bytes_per_sec = total_rate / len(recent_sessions)

        return average_rate_bytes_per_sec / (1024**2)  # Convert to Mbps

    def _calculate_average_transfer_rate_mbps(self) -> float:
        """Calculate overall average transfer rate"""
        if not self._completed_sessions:
            return 0.0

        total_bytes = sum(
            session.bytes_transferred for session in self._completed_sessions
        )
        total_duration = sum(
            session.duration_seconds for session in self._completed_sessions
        )

        if total_duration > 0:
            average_rate_bytes_per_sec = total_bytes / total_duration
            return average_rate_bytes_per_sec / (1024**2)  # Convert to Mbps

        return 0.0

    def reset_statistics(self, keep_session_tracking: bool = True) -> None:
        """
        Reset all statistics for testing eller maintenance.

        Args:
            keep_session_tracking: Whether to preserve session tracking state
        """
        with self._lock:
            self._total_files_copied = 0
            self._total_files_failed = 0
            self._total_bytes_copied = 0
            self._peak_transfer_rate = 0.0
            self._session_start_time = datetime.now()
            self._last_activity_time = datetime.now()

            if not keep_session_tracking:
                self._active_sessions.clear()
                self._completed_sessions.clear()

            logging.info("Statistics reset completed")

    def get_active_sessions(self) -> List[Dict[str, Any]]:
        """
        Get details about currently active copy sessions.

        Returns:
            List of active session details
        """
        with self._lock:
            return [
                {
                    "file_path": session.file_path,
                    "file_size": session.file_size,
                    "bytes_transferred": session.bytes_transferred,
                    "progress_percent": (
                        session.bytes_transferred / session.file_size * 100
                    )
                    if session.file_size > 0
                    else 0,
                    "duration_seconds": session.duration_seconds,
                    "transfer_rate_mbps": session.transfer_rate_bytes_per_sec
                    / (1024**2),
                    "retry_count": session.retry_count,
                    "copy_strategy": session.copy_strategy,
                    "started_at": session.started_at.isoformat(),
                }
                for session in self._active_sessions.values()
            ]

    def cleanup_stale_sessions(self, max_age_hours: float = 24.0) -> int:
        """
        Clean up stale active sessions som might be stuck.

        Args:
            max_age_hours: Maximum age in hours before session is considered stale

        Returns:
            Number of sessions cleaned up
        """
        max_age = timedelta(hours=max_age_hours)
        now = datetime.now()
        cleaned_count = 0

        with self._lock:
            stale_paths = []

            for file_path, session in self._active_sessions.items():
                if now - session.started_at > max_age:
                    stale_paths.append(file_path)

            for file_path in stale_paths:
                session = self._active_sessions.pop(file_path)
                logging.warning(
                    f"Cleaned up stale session: {file_path} (age: {(now - session.started_at).total_seconds() / 3600:.1f}h)"
                )
                cleaned_count += 1

        if cleaned_count > 0:
            logging.info(f"Cleaned up {cleaned_count} stale sessions")

        return cleaned_count
