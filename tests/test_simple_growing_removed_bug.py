"""
Test to verify that files disappearing during growing->copying transition are properly handled.

This test confirms the fix for the bug where files remain stuck in COPYING status
instead of being marked as REMOVED when the source file disappears.
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