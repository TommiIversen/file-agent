"""
Simplified test for growing file removed bug - focuses on error classification.
"""

import pytest
from unittest.mock import Mock, patch
from pathlib import Path

from app.models import FileStatus
from app.services.consumer.job_error_classifier import JobErrorClassifier


class TestGrowingFileRemovedBug:
    """Test that file removal during copying is properly classified."""

    @pytest.fixture
    def error_classifier(self):
        storage_monitor = Mock()
        storage_monitor.get_destination_info.return_value = None
        return JobErrorClassifier(storage_monitor)

    def test_file_not_found_during_copying_should_be_removed(self, error_classifier):
        """
        Test that FileNotFoundError during copying is classified as REMOVED.
        
        This reproduces the bug where files disappearing during copying 
        remain stuck in COPYING status instead of being marked as REMOVED.
        """
        file_path = "/test/source/growing_file.mxf"
        
        # Simulate the exact error from the log
        error = FileNotFoundError(
            "[WinError 2] The system cannot find the file specified: "
            f"'{file_path}'"
        )
        
        # Mock Path.exists to return False (file doesn't exist)
        with patch.object(Path, 'exists', return_value=False):
            status, reason = error_classifier.classify_copy_error(error, file_path)
            
            # Should be classified as REMOVED, not FAILED
            assert status == FileStatus.REMOVED, f"Expected REMOVED, got {status}"
            assert "no longer exists" in reason, f"Expected 'no longer exists' in reason, got: {reason}"

    def test_file_exists_but_other_source_error_should_fail(self, error_classifier):
        """
        Test that source errors where file still exists should be FAILED, not REMOVED.
        """
        file_path = "/test/source/locked_file.mxf"
        
        # Different source error - file exists but is locked
        error = PermissionError(f"Permission denied: '{file_path}'")
        
        # File still exists
        with patch.object(Path, 'exists', return_value=True):
            status, reason = error_classifier.classify_copy_error(error, file_path)
            
            # Should be FAILED since file exists but has other issue
            assert status == FileStatus.FAILED, f"Expected FAILED, got {status}"

    def test_network_error_should_pause(self, error_classifier):
        """
        Test that network errors are still classified as PAUSED_COPYING.
        """
        file_path = "/test/source/network_file.mxf"
        
        # Network error
        error = ConnectionError("Network connection failed")
        
        with patch.object(Path, 'exists', return_value=True):
            status, reason = error_classifier.classify_copy_error(error, file_path)
            
            # Should be PAUSED_COPYING for network issues
            assert status == FileStatus.PAUSED_COPYING, f"Expected PAUSED_COPYING, got {status}"

    def test_growing_copy_file_stat_error_classification(self, error_classifier):
        """
        Test the specific error from the log: source.stat().st_size failing.
        """
        file_path = "c:\\temp_input\\Ingest_Cam1.mxf"
        
        # Exact error from log - trying to get file stats when file doesn't exist
        error = FileNotFoundError(
            "[WinError 2] The system cannot find the file specified: "
            f"'{file_path}'"
        )
        
        # File has been deleted
        with patch.object(Path, 'exists', return_value=False):
            status, reason = error_classifier.classify_copy_error(error, file_path)
            
            # BUG REPRODUCTION: Currently this might not work correctly
            # Should be REMOVED when source file disappears during copying
            assert status == FileStatus.REMOVED, (
                f"BUG: File that disappeared during copying should be REMOVED, got {status}. "
                f"This means the file will stay stuck in COPYING status in UI."
            )
            
            print(f"✅ SUCCESS: Error correctly classified as {status} with reason: {reason}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])