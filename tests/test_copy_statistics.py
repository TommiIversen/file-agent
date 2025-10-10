"""
Tests for CopyStatisticsTracker Strategy.

Test suite for statistics tracking strategy that manages copy metrics,
performance monitoring, and session tracking.
"""

import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import patch

from app.config import Settings
from app.services.tracking.copy_statistics import (
    CopyStatisticsTracker,
    CopySession,
    StatisticsSummary
)


@pytest.fixture
def settings():
    """Create test settings"""
    return Settings(
        source_directory="C:/source",
        destination_directory="C:/dest",
        max_retry_attempts=3,
        retry_delay_seconds=1,
        global_retry_delay_seconds=5
    )


@pytest.fixture
def stats_tracker(settings):
    """Create CopyStatisticsTracker instance"""
    return CopyStatisticsTracker(settings, enable_session_tracking=True)


@pytest.fixture
def stats_tracker_no_sessions(settings):
    """Create CopyStatisticsTracker instance without session tracking"""
    return CopyStatisticsTracker(settings, enable_session_tracking=False)


class TestCopySession:
    """Test CopySession dataclass functionality"""
    
    def test_copy_session_creation(self):
        """Test CopySession creation and basic properties"""
        start_time = datetime.now()
        session = CopySession(
            file_path="/test/file.txt",
            file_size=1000,
            started_at=start_time
        )
        
        assert session.file_path == "/test/file.txt"
        assert session.file_size == 1000
        assert session.started_at == start_time
        assert session.completed_at is None
        assert session.bytes_transferred == 0
        assert session.is_completed is False
    
    def test_copy_session_duration(self):
        """Test duration calculation"""
        start_time = datetime.now()
        session = CopySession(
            file_path="/test/file.txt",
            file_size=1000,
            started_at=start_time
        )
        
        # Test active session duration
        duration = session.duration_seconds
        assert duration >= 0
        assert duration < 1  # Should be very small
        
        # Test completed session duration
        session.completed_at = start_time + timedelta(seconds=5)
        assert session.duration_seconds == 5.0
        assert session.is_completed is True
    
    def test_transfer_rate_calculation(self):
        """Test transfer rate calculation"""
        start_time = datetime.now()
        session = CopySession(
            file_path="/test/file.txt",
            file_size=1000,
            started_at=start_time,
            bytes_transferred=500
        )
        
        session.completed_at = start_time + timedelta(seconds=2)
        
        # 500 bytes in 2 seconds = 250 bytes/sec
        assert session.transfer_rate_bytes_per_sec == 250.0


class TestStatisticsSummary:
    """Test StatisticsSummary dataclass functionality"""
    
    def test_statistics_summary_creation(self):
        """Test StatisticsSummary creation"""
        summary = StatisticsSummary(
            total_files_copied=10,
            total_files_failed=2,
            total_bytes_copied=1024**3  # 1 GB
        )
        
        assert summary.total_files_copied == 10
        assert summary.total_files_failed == 2
        assert summary.total_gb_copied == 1.0
    
    def test_success_rate_calculation(self):
        """Test success rate calculation"""
        summary = StatisticsSummary(
            total_files_copied=8,
            total_files_failed=2
        )
        
        # 8 success out of 10 total = 80%
        assert summary.success_rate == 80.0
        
        # Test with no attempts
        empty_summary = StatisticsSummary()
        assert empty_summary.success_rate == 0.0
    
    def test_average_file_size_calculation(self):
        """Test average file size calculation"""
        summary = StatisticsSummary(
            total_files_copied=4,
            total_bytes_copied=4 * 1024**2  # 4 MB total
        )
        
        # 4 MB / 4 files = 1 MB average
        assert summary.average_file_size_mb == 1.0
        
        # Test with no files
        empty_summary = StatisticsSummary()
        assert empty_summary.average_file_size_mb == 0.0


class TestBasicStatisticsTracking:
    """Test basic statistics tracking functionality"""
    
    def test_initial_state(self, stats_tracker):
        """Test initial tracker state"""
        summary = stats_tracker.get_statistics_summary()
        
        assert summary.total_files_copied == 0
        assert summary.total_files_failed == 0
        assert summary.total_bytes_copied == 0
        assert summary.active_sessions == 0
        assert summary.completed_sessions == 0
    
    def test_successful_copy_tracking(self, stats_tracker):
        """Test tracking successful copy without session tracking"""
        # Complete a successful copy
        stats_tracker.complete_copy_session("/test/file1.txt", success=True, final_bytes_transferred=1000)
        
        summary = stats_tracker.get_statistics_summary()
        assert summary.total_files_copied == 1
        assert summary.total_files_failed == 0
        assert summary.total_bytes_copied == 1000
    
    def test_failed_copy_tracking(self, stats_tracker):
        """Test tracking failed copy"""
        # Complete a failed copy
        stats_tracker.complete_copy_session("/test/file1.txt", success=False)
        
        summary = stats_tracker.get_statistics_summary()
        assert summary.total_files_copied == 0
        assert summary.total_files_failed == 1
        assert summary.total_bytes_copied == 0
    
    def test_mixed_copy_tracking(self, stats_tracker):
        """Test tracking mix of successful and failed copies"""
        # Track multiple copies
        stats_tracker.complete_copy_session("/test/file1.txt", success=True, final_bytes_transferred=1000)
        stats_tracker.complete_copy_session("/test/file2.txt", success=False)
        stats_tracker.complete_copy_session("/test/file3.txt", success=True, final_bytes_transferred=2000)
        
        summary = stats_tracker.get_statistics_summary()
        assert summary.total_files_copied == 2
        assert summary.total_files_failed == 1
        assert summary.total_bytes_copied == 3000
        assert summary.success_rate == pytest.approx(66.67, rel=1e-2)  # 2 out of 3
    
    def test_statistics_without_session_tracking(self, stats_tracker_no_sessions):
        """Test statistics tracking when session tracking is disabled"""
        # Complete copies without session tracking
        stats_tracker_no_sessions.complete_copy_session("/test/file1.txt", success=True, final_bytes_transferred=1000)
        stats_tracker_no_sessions.complete_copy_session("/test/file2.txt", success=False)
        
        summary = stats_tracker_no_sessions.get_statistics_summary()
        assert summary.total_files_copied == 1
        assert summary.total_files_failed == 1
        assert summary.total_bytes_copied == 1000
        assert summary.active_sessions == 0
        assert summary.completed_sessions == 0  # No session tracking


class TestSessionTracking:
    """Test session tracking functionality"""
    
    def test_session_lifecycle(self, stats_tracker):
        """Test complete session lifecycle"""
        # Start session
        stats_tracker.start_copy_session("/test/file.txt", 1000, "NormalCopyStrategy")
        
        summary = stats_tracker.get_statistics_summary()
        assert summary.active_sessions == 1
        assert summary.completed_sessions == 0
        
        # Update progress
        stats_tracker.update_session_progress("/test/file.txt", 500)
        
        # Complete session
        stats_tracker.complete_copy_session("/test/file.txt", success=True, final_bytes_transferred=1000)
        
        summary = stats_tracker.get_statistics_summary()
        assert summary.active_sessions == 0
        assert summary.completed_sessions == 1
        assert summary.total_files_copied == 1
        assert summary.total_bytes_copied == 1000
    
    def test_multiple_concurrent_sessions(self, stats_tracker):
        """Test multiple concurrent sessions"""
        # Start multiple sessions
        stats_tracker.start_copy_session("/test/file1.txt", 1000)
        stats_tracker.start_copy_session("/test/file2.txt", 2000)
        stats_tracker.start_copy_session("/test/file3.txt", 3000)
        
        summary = stats_tracker.get_statistics_summary()
        assert summary.active_sessions == 3
        
        # Complete one session
        stats_tracker.complete_copy_session("/test/file1.txt", success=True, final_bytes_transferred=1000)
        
        summary = stats_tracker.get_statistics_summary()
        assert summary.active_sessions == 2
        assert summary.completed_sessions == 1
        
        # Complete remaining sessions
        stats_tracker.complete_copy_session("/test/file2.txt", success=False)
        stats_tracker.complete_copy_session("/test/file3.txt", success=True, final_bytes_transferred=3000)
        
        summary = stats_tracker.get_statistics_summary()
        assert summary.active_sessions == 0
        assert summary.completed_sessions == 3
        assert summary.total_files_copied == 2
        assert summary.total_files_failed == 1
    
    def test_session_progress_updates(self, stats_tracker):
        """Test session progress updates"""
        # Start session
        stats_tracker.start_copy_session("/test/file.txt", 1000)
        
        # Update progress multiple times
        stats_tracker.update_session_progress("/test/file.txt", 250)
        stats_tracker.update_session_progress("/test/file.txt", 500)
        stats_tracker.update_session_progress("/test/file.txt", 750)
        
        # Check active session details
        active_sessions = stats_tracker.get_active_sessions()
        assert len(active_sessions) == 1
        assert active_sessions[0]["bytes_transferred"] == 750
        assert active_sessions[0]["progress_percent"] == 75.0
    
    def test_retry_count_tracking(self, stats_tracker):
        """Test retry count tracking"""
        # Start session
        stats_tracker.start_copy_session("/test/file.txt", 1000)
        
        # Increment retry count
        stats_tracker.increment_retry_count("/test/file.txt")
        stats_tracker.increment_retry_count("/test/file.txt")
        
        # Check retry count
        active_sessions = stats_tracker.get_active_sessions()
        assert active_sessions[0]["retry_count"] == 2
        
        # Complete session
        stats_tracker.complete_copy_session("/test/file.txt", success=True, final_bytes_transferred=1000)
        
        # Check completed session details
        detailed_stats = stats_tracker.get_detailed_statistics()
        recent_summary = detailed_stats["sessions"]["recent_completed_summary"]
        assert recent_summary["count"] == 1


class TestPerformanceMetrics:
    """Test performance metrics calculation"""
    
    def test_transfer_rate_calculation(self, stats_tracker):
        """Test transfer rate calculation with real timing"""
        # Mock datetime to control timing
        start_time = datetime(2023, 1, 1, 12, 0, 0)
        
        with patch('app.services.tracking.copy_statistics.datetime') as mock_dt:
            mock_dt.now.return_value = start_time
            
            # Start session
            stats_tracker.start_copy_session("/test/file.txt", 1000)
            
            # Mock completion time (2 seconds later)
            mock_dt.now.return_value = start_time + timedelta(seconds=2)
            
            # Complete session
            stats_tracker.complete_copy_session("/test/file.txt", success=True, final_bytes_transferred=1000)
        
        summary = stats_tracker.get_statistics_summary()
        
        # Transfer rate should be calculated: 1000 bytes / 2 seconds = 500 bytes/sec = ~0.48 Mbps
        assert summary.average_transfer_rate_mbps > 0
        assert summary.peak_transfer_rate_mbps > 0
    
    def test_peak_rate_tracking(self, stats_tracker):
        """Test peak transfer rate tracking"""
        start_time = datetime(2023, 1, 1, 12, 0, 0)
        
        with patch('app.services.tracking.copy_statistics.datetime') as mock_dt:
            # First session - slower rate
            mock_dt.now.return_value = start_time
            stats_tracker.start_copy_session("/test/file1.txt", 1000)
            mock_dt.now.return_value = start_time + timedelta(seconds=4)  # 250 bytes/sec
            stats_tracker.complete_copy_session("/test/file1.txt", success=True, final_bytes_transferred=1000)
            
            # Second session - faster rate
            mock_dt.now.return_value = start_time + timedelta(seconds=5)
            stats_tracker.start_copy_session("/test/file2.txt", 2000)
            mock_dt.now.return_value = start_time + timedelta(seconds=6)  # 2000 bytes/sec
            stats_tracker.complete_copy_session("/test/file2.txt", success=True, final_bytes_transferred=2000)
        
        summary = stats_tracker.get_statistics_summary()
        
        # Peak rate should reflect the faster session
        peak_rate_bytes_per_sec = summary.peak_transfer_rate_mbps * (1024**2)
        assert peak_rate_bytes_per_sec > 1500  # Should be close to 2000 bytes/sec


class TestDetailedStatistics:
    """Test detailed statistics reporting"""
    
    def test_detailed_statistics_structure(self, stats_tracker):
        """Test detailed statistics structure"""
        # Create some test data
        stats_tracker.start_copy_session("/test/file1.txt", 1000, "NormalCopyStrategy")
        stats_tracker.complete_copy_session("/test/file2.txt", success=True, final_bytes_transferred=2000)
        stats_tracker.complete_copy_session("/test/file3.txt", success=False)
        
        detailed_stats = stats_tracker.get_detailed_statistics()
        
        # Check structure
        expected_keys = {"summary", "performance", "sessions", "timing", "config"}
        assert set(detailed_stats.keys()) == expected_keys
        
        # Check summary section
        summary = detailed_stats["summary"]
        assert "total_files_copied" in summary
        assert "total_files_failed" in summary
        assert "success_rate" in summary
        
        # Check performance section
        performance = detailed_stats["performance"]
        assert "current_transfer_rate_mbps" in performance
        assert "average_transfer_rate_mbps" in performance
        assert "peak_transfer_rate_mbps" in performance
        
        # Check sessions section
        sessions = detailed_stats["sessions"]
        assert "active_count" in sessions
        assert "completed_count" in sessions
        assert "active_details" in sessions
    
    def test_active_session_details(self, stats_tracker):
        """Test active session details"""
        # Start sessions with different progress
        stats_tracker.start_copy_session("/test/file1.txt", 1000, "NormalCopyStrategy")
        stats_tracker.start_copy_session("/test/file2.txt", 2000, "GrowingCopyStrategy")
        
        # Update progress
        stats_tracker.update_session_progress("/test/file1.txt", 500)
        stats_tracker.update_session_progress("/test/file2.txt", 1000)
        
        active_sessions = stats_tracker.get_active_sessions()
        
        assert len(active_sessions) == 2
        
        # Check session details
        session1 = next(s for s in active_sessions if s["file_path"] == "/test/file1.txt")
        assert session1["progress_percent"] == 50.0
        assert session1["copy_strategy"] == "NormalCopyStrategy"
        
        session2 = next(s for s in active_sessions if s["file_path"] == "/test/file2.txt")
        assert session2["progress_percent"] == 50.0
        assert session2["copy_strategy"] == "GrowingCopyStrategy"


class TestMemoryManagement:
    """Test memory management and cleanup functionality"""
    
    def test_completed_sessions_limit(self, settings):
        """Test completed sessions memory limit"""
        # Create tracker with small limit
        tracker = CopyStatisticsTracker(settings, enable_session_tracking=True)
        tracker._max_completed_sessions = 3
        
        # Complete more sessions than limit - start sessions first
        for i in range(5):
            file_path = f"/test/file{i}.txt"
            tracker.start_copy_session(file_path, 1000)
            tracker.complete_copy_session(file_path, success=True, final_bytes_transferred=1000)
        
        summary = tracker.get_statistics_summary()
        assert summary.completed_sessions == 3  # Should be limited to max
        assert summary.total_files_copied == 5   # Counters should still be accurate
    
    def test_stale_session_cleanup(self, stats_tracker):
        """Test cleanup of stale active sessions"""
        # Start sessions and manually age them
        stats_tracker.start_copy_session("/test/file1.txt", 1000)
        stats_tracker.start_copy_session("/test/file2.txt", 1000)
        
        # Manually age one session
        old_time = datetime.now() - timedelta(hours=25)  # 25 hours ago
        stats_tracker._active_sessions["/test/file1.txt"].started_at = old_time
        
        # Cleanup stale sessions (max age 24 hours)
        cleaned_count = stats_tracker.cleanup_stale_sessions(max_age_hours=24.0)
        
        assert cleaned_count == 1
        
        summary = stats_tracker.get_statistics_summary()
        assert summary.active_sessions == 1  # Only one session should remain


class TestStatisticsReset:
    """Test statistics reset functionality"""
    
    def test_complete_reset(self, stats_tracker):
        """Test complete statistics reset"""
        # Create some test data
        stats_tracker.start_copy_session("/test/file1.txt", 1000)
        stats_tracker.complete_copy_session("/test/file2.txt", success=True, final_bytes_transferred=2000)
        stats_tracker.complete_copy_session("/test/file3.txt", success=False)
        
        # Verify data exists
        summary_before = stats_tracker.get_statistics_summary()
        assert summary_before.total_files_copied > 0
        assert summary_before.active_sessions > 0
        
        # Reset everything
        stats_tracker.reset_statistics(keep_session_tracking=False)
        
        # Verify reset
        summary_after = stats_tracker.get_statistics_summary()
        assert summary_after.total_files_copied == 0
        assert summary_after.total_files_failed == 0
        assert summary_after.total_bytes_copied == 0
        assert summary_after.active_sessions == 0
        assert summary_after.completed_sessions == 0
    
    def test_partial_reset(self, stats_tracker):
        """Test partial reset keeping session tracking"""
        # Create test data
        stats_tracker.start_copy_session("/test/file1.txt", 1000)
        stats_tracker.complete_copy_session("/test/file2.txt", success=True, final_bytes_transferred=2000)
        
        sessions_before = stats_tracker.get_statistics_summary().active_sessions
        
        # Reset but keep sessions
        stats_tracker.reset_statistics(keep_session_tracking=True)
        
        summary = stats_tracker.get_statistics_summary()
        assert summary.total_files_copied == 0  # Counters reset
        assert summary.active_sessions == sessions_before  # Sessions preserved


class TestThreadSafety:
    """Test thread safety of statistics tracking"""
    
    def test_concurrent_operations(self, stats_tracker):
        """Test concurrent statistics operations"""
        import threading
        import random
        
        def worker():
            for i in range(10):
                file_path = f"/test/worker_file_{threading.current_thread().ident}_{i}.txt"
                stats_tracker.start_copy_session(file_path, 1000)
                time.sleep(0.001)  # Small delay
                stats_tracker.update_session_progress(file_path, 500)
                time.sleep(0.001)
                success = random.choice([True, False])
                final_bytes = 1000 if success else None
                stats_tracker.complete_copy_session(file_path, success, final_bytes)
        
        # Run multiple workers concurrently
        threads = []
        for _ in range(3):
            thread = threading.Thread(target=worker)
            threads.append(thread)
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        # Verify final state is consistent
        summary = stats_tracker.get_statistics_summary()
        total_operations = summary.total_files_copied + summary.total_files_failed
        assert total_operations == 30  # 3 workers * 10 operations each
        assert summary.active_sessions == 0  # All sessions should be completed


class TestEdgeCases:
    """Test edge cases and error conditions"""
    
    def test_operations_on_nonexistent_session(self, stats_tracker):
        """Test operations on non-existent sessions"""
        # These operations should not crash
        stats_tracker.update_session_progress("/nonexistent/file.txt", 500)
        stats_tracker.increment_retry_count("/nonexistent/file.txt")
        
        # Should still work normally
        summary = stats_tracker.get_statistics_summary()
        assert summary.active_sessions == 0
    
    def test_zero_size_files(self, stats_tracker):
        """Test handling of zero-size files"""
        stats_tracker.start_copy_session("/test/empty.txt", 0)
        
        active_sessions = stats_tracker.get_active_sessions()
        assert active_sessions[0]["progress_percent"] == 0
        
        stats_tracker.complete_copy_session("/test/empty.txt", success=True, final_bytes_transferred=0)
        
        summary = stats_tracker.get_statistics_summary()
        assert summary.total_files_copied == 1
        assert summary.total_bytes_copied == 0
    
    def test_session_tracking_disabled_operations(self, stats_tracker_no_sessions):
        """Test session tracking operations when disabled"""
        # These should not crash but also not track sessions
        stats_tracker_no_sessions.start_copy_session("/test/file.txt", 1000)
        stats_tracker_no_sessions.update_session_progress("/test/file.txt", 500)
        stats_tracker_no_sessions.increment_retry_count("/test/file.txt")
        
        summary = stats_tracker_no_sessions.get_statistics_summary()
        assert summary.active_sessions == 0
        assert summary.completed_sessions == 0
        
        # But statistics should still work
        stats_tracker_no_sessions.complete_copy_session("/test/file.txt", success=True, final_bytes_transferred=1000)
        
        summary = stats_tracker_no_sessions.get_statistics_summary()
        assert summary.total_files_copied == 1
        assert summary.total_bytes_copied == 1000