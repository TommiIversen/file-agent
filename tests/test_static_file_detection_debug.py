"""
Debug test for static file detection in real scenario.

This test simulates the exact scenario from your log to understand why static files are 
being detected as growing files.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import Settings
from app.models import FileStatus, TrackedFile
from app.services.copy_strategies import GrowingFileCopyStrategy
from app.services.copy.file_copy_executor import FileCopyExecutor
from app.services.state_manager import StateManager


class TestStaticFileDetectionDebug:
    """Debug the actual static file detection issue."""

    @pytest.fixture
    def settings(self):
        """Create test settings."""
        settings = MagicMock(spec=Settings)
        settings.growing_file_min_size_mb = 100  # 100MB minimum
        settings.growing_file_safety_margin_mb = 50  # 50MB safety margin
        settings.growing_file_chunk_size_kb = 2048  # 2MB chunks
        settings.growing_file_poll_interval_seconds = 5
        settings.growing_copy_pause_ms = 100
        settings.growing_file_growth_timeout_seconds = 30
        return settings

    @pytest.fixture
    def state_manager(self):
        """Mock state manager."""
        return AsyncMock(spec=StateManager)

    @pytest.fixture
    def file_copy_executor(self):
        """Mock file copy executor."""
        return MagicMock(spec=FileCopyExecutor)

    @pytest.fixture
    def copy_strategy(self, settings, state_manager, file_copy_executor):
        """Create GrowingFileCopyStrategy for testing."""
        return GrowingFileCopyStrategy(settings, state_manager, file_copy_executor)

    def test_debug_file_from_log_exact_scenario(self, copy_strategy):
        """
        Test the exact file from your log to see why it's detected as growing.
        
        From the log:
        - File: TOMMI_Passengers_Breakfast_4K.mxf
        - Size: 225,999,953 bytes (~216MB)
        - Status progression: DISCOVERED -> READY -> IN_QUEUE -> GROWING_COPY
        
        This should be detected as static since it's READY status with no growth history.
        """
        # Recreate the file from your log as it would appear when copy starts
        file_from_log = TrackedFile(
            file_path="c:/temp_input/TOMMI_Passengers_Breakfast_4K.mxf",
            file_size=225_999_953,  # Exact size from log
            status=FileStatus.READY,  # Status before IN_QUEUE
            growth_rate_mbps=0.0,  # From log: (rate: 0.00MB/s)
            first_seen_size=225_999_953,  # Likely same size since static
            previous_file_size=225_999_953,  # Likely same size since static
        )

        print(f"\n=== DEBUG FILE DETECTION ===")
        print(f"File: {file_from_log.file_path}")
        print(f"Size: {file_from_log.file_size:,} bytes ({file_from_log.file_size/(1024*1024):.1f}MB)")
        print(f"Status: {file_from_log.status}")
        print(f"Growth rate: {file_from_log.growth_rate_mbps}MB/s")
        print(f"First seen size: {file_from_log.first_seen_size:,}")
        print(f"Previous size: {file_from_log.previous_file_size:,}")
        
        # Test the detection
        result = copy_strategy._is_file_currently_growing(file_from_log)
        
        print(f"Detection result: {result}")
        print(f"Expected: False (static file)")
        
        # Detailed debug of each condition
        print(f"\n=== CONDITION CHECKS ===")
        
        # Check 1: Status-based detection
        growing_statuses = [FileStatus.GROWING, FileStatus.READY_TO_START_GROWING, FileStatus.GROWING_COPY]
        status_check = file_from_log.status in growing_statuses
        print(f"1. Growing status check: {status_check} (status: {file_from_log.status})")
        
        # Check 2: Growth rate
        growth_rate_check = file_from_log.growth_rate_mbps > 0
        print(f"2. Growth rate check: {growth_rate_check} (rate: {file_from_log.growth_rate_mbps})")
        
        # Check 3: Size increase since first seen
        size_increase_check = (file_from_log.first_seen_size > 0 and 
                              file_from_log.file_size > file_from_log.first_seen_size)
        print(f"3. Size increase check: {size_increase_check} (current: {file_from_log.file_size:,}, first: {file_from_log.first_seen_size:,})")
        
        # Check 4: Recent size change
        recent_change_check = (file_from_log.previous_file_size > 0 and 
                              file_from_log.file_size != file_from_log.previous_file_size)
        print(f"4. Recent change check: {recent_change_check} (current: {file_from_log.file_size:,}, previous: {file_from_log.previous_file_size:,})")
        
        print(f"\n=== OVERALL RESULT ===")
        print(f"Any condition true: {status_check or growth_rate_check or size_increase_check or recent_change_check}")
        print(f"Should be static: {not result}")
        
        assert result is False, f"File should be detected as static but was detected as growing. Failing conditions: status={status_check}, rate={growth_rate_check}, size_inc={size_increase_check}, recent={recent_change_check}"

    def test_debug_possible_growing_statuses(self, copy_strategy):
        """
        Test if the file might have a different status than expected.
        """
        # Test each status that could cause growing detection
        statuses_to_test = [
            FileStatus.DISCOVERED,
            FileStatus.READY,
            FileStatus.READY_TO_START_GROWING,
            FileStatus.GROWING,
            FileStatus.IN_QUEUE,
            FileStatus.GROWING_COPY,
        ]
        
        print(f"\n=== STATUS DETECTION TEST ===")
        for status in statuses_to_test:
            test_file = TrackedFile(
                file_path="test.mxf",
                file_size=225_999_953,
                status=status,
                growth_rate_mbps=0.0,
                first_seen_size=225_999_953,
                previous_file_size=225_999_953,
            )
            
            result = copy_strategy._is_file_currently_growing(test_file)
            print(f"Status {status}: {'GROWING' if result else 'STATIC'}")

    def test_debug_possible_size_history_issues(self, copy_strategy):
        """
        Test different size history scenarios that might cause issues.
        """
        print(f"\n=== SIZE HISTORY TEST ===")
        
        # Scenario 1: first_seen_size = 0 (might cause issues)
        test1 = TrackedFile(
            file_path="test.mxv",
            file_size=225_999_953,
            status=FileStatus.READY,
            growth_rate_mbps=0.0,
            first_seen_size=0,  # Zero might be problematic
            previous_file_size=225_999_953,
        )
        result1 = copy_strategy._is_file_currently_growing(test1)
        print(f"Zero first_seen_size: {'GROWING' if result1 else 'STATIC'}")
        
        # Scenario 2: previous_file_size = 0
        test2 = TrackedFile(
            file_path="test.mxv",
            file_size=225_999_953,
            status=FileStatus.READY,
            growth_rate_mbps=0.0,
            first_seen_size=225_999_953,
            previous_file_size=0,  # Zero might be problematic
        )
        result2 = copy_strategy._is_file_currently_growing(test2)
        print(f"Zero previous_file_size: {'GROWING' if result2 else 'STATIC'}")
        
        # Scenario 3: Slight size difference (maybe from file system precision)
        test3 = TrackedFile(
            file_path="test.mxv",
            file_size=225_999_953,
            status=FileStatus.READY,
            growth_rate_mbps=0.0,
            first_seen_size=225_999_952,  # Off by 1 byte
            previous_file_size=225_999_953,
        )
        result3 = copy_strategy._is_file_currently_growing(test3)
        print(f"Size diff by 1 byte: {'GROWING' if result3 else 'STATIC'}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])