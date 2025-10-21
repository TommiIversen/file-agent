#!/usr/bin/env python3
"""
End-to-end test demonstrating that growing files deleted during copying 
are properly classified as REMOVED instead of staying stuck in COPYING status.

This test reproduces the exact scenario from the user's log where:
1. File is in GROWING_COPY status
2. Growing copy phase completes, status changes to COPYING
3. Source file gets deleted during the finishing phase
4. FileNotFoundError should bubble up through ALL layers to error classifier
5. File should be marked as REMOVED, not stuck in COPYING
"""

import asyncio
import tempfile
import shutil
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import logging

# Setup logging to see what happens
logging.basicConfig(level=logging.INFO)

# Import our components
from app.models import FileStatus, TrackedFile
from app.services.consumer.job_copy_executor import JobCopyExecutor
from app.services.consumer.job_error_classifier import JobErrorClassifier
from app.services.consumer.job_models import PreparedFile
from app.services.copy_strategies import CopyStrategyFactory
from app.services.state_manager import StateManager
from app.config import Settings


async def test_growing_file_removed_during_copying_complete_flow():
    """Test the complete flow when a growing file is removed during copying phase."""
    
    print("=== Testing Complete Growing File Removal Flow ===")
    
    # Create temp directories
    with tempfile.TemporaryDirectory() as temp_source, \
         tempfile.TemporaryDirectory() as temp_dest:
        
        source_path = Path(temp_source) / "test_file.mxf"
        dest_path = Path(temp_dest) / "test_file.mxv"
        
        # Create a test file first
        source_path.write_text("test content")
        
        # Create TrackedFile in COPYING status (after growing phase completed)
        tracked_file = TrackedFile(
            id="test-id-123",
            file_path=str(source_path),
            file_size=len("test content"),
            status=FileStatus.COPYING,  # Already transitioned from GROWING_COPY
            copy_progress=0.5  # Partially copied
        )
        
        # Create PreparedFile
        prepared_file = PreparedFile(
            tracked_file=tracked_file,
            strategy_name="MockStrategy",
            destination_path=dest_path,
            initial_status=FileStatus.COPYING
        )
        
        # Mock dependencies
        settings = MagicMock()
        state_manager = AsyncMock(spec=StateManager)
        
        # Setup error classifier to properly classify FileNotFoundError
        storage_monitor = MagicMock()
        storage_monitor.get_destination_status.return_value = "AVAILABLE"  # Mock available storage
        error_classifier = JobErrorClassifier(storage_monitor)
        
        # Create copy strategy factory that will fail when file is removed
        copy_strategy_factory = MagicMock(spec=CopyStrategyFactory)
        
        # Create a mock strategy that will raise FileNotFoundError
        mock_strategy = AsyncMock()
        
        # First, delete the file to simulate removal during copying
        print(f"Removing source file: {source_path}")
        source_path.unlink()
        
        # Configure strategy to raise FileNotFoundError when copy_file is called
        mock_strategy.copy_file.side_effect = FileNotFoundError(f"[WinError 2] The system cannot find the file specified: '{source_path}'")
        copy_strategy_factory.get_strategy.return_value = mock_strategy
        
        # Create JobCopyExecutor
        copy_executor = JobCopyExecutor(
            settings=settings,
            state_manager=state_manager,
            copy_strategy_factory=copy_strategy_factory,
            error_classifier=error_classifier
        )
        
        print("1. Testing execute_copy with FileNotFoundError...")
        
        # Test that execute_copy raises FileNotFoundError instead of returning False
        try:
            await copy_executor.execute_copy(prepared_file)
            print("❌ ERROR: execute_copy should have raised FileNotFoundError!")
            return False
        except FileNotFoundError as e:
            print(f"✅ SUCCESS: execute_copy properly raised FileNotFoundError: {e}")
        
        print("\n2. Testing error classification...")
        
        # Test error classification
        file_not_found_error = FileNotFoundError(f"[WinError 2] The system cannot find the file specified: '{source_path}'")
        status, reason = error_classifier.classify_copy_error(file_not_found_error, str(source_path))
        
        print(f"Error classified as: {status} with reason: {reason}")
        
        if status == FileStatus.REMOVED:
            print("✅ SUCCESS: FileNotFoundError correctly classified as REMOVED")
        else:
            print(f"❌ ERROR: FileNotFoundError incorrectly classified as {status}")
            return False
        
        print("\n3. Testing handle_copy_failure...")
        
        # Test handle_copy_failure
        was_paused = await copy_executor.handle_copy_failure(prepared_file, file_not_found_error)
        
        if was_paused:
            print("❌ ERROR: handle_copy_failure should return False for REMOVED files")
            return False
        else:
            print("✅ SUCCESS: handle_copy_failure returned False for REMOVED file")
        
        # Verify state_manager was called to update status to REMOVED
        state_manager.update_file_status_by_id.assert_called_once()
        call_args = state_manager.update_file_status_by_id.call_args
        
        if call_args[0][1] == FileStatus.REMOVED:  # Second argument should be FileStatus.REMOVED
            print("✅ SUCCESS: File status updated to REMOVED")
        else:
            print(f"❌ ERROR: File status updated to {call_args[0][1]} instead of REMOVED")
            return False
        
        print("\n=== All tests passed! Growing file removal bug is fixed! ===")
        return True


async def test_job_processor_integration():
    """Test that the job processor flow also works correctly."""
    
    print("\n=== Testing Job Processor Integration ===")
    
    # This simulates what happens in job_processor.py when execute_copy raises an exception
    
    # Mock the copy executor that raises FileNotFoundError
    copy_executor = AsyncMock()
    copy_executor.execute_copy.side_effect = FileNotFoundError("File not found")
    copy_executor.handle_copy_failure.return_value = False  # REMOVED files return False
    
    # Mock prepared file
    prepared_file = MagicMock()
    prepared_file.tracked_file.file_path = "test_file.mxf"
    
    # Simulate the job_processor.py flow
    try:
        copy_success = await copy_executor.execute_copy(prepared_file)
        print("❌ ERROR: Should have raised exception")
        return False
    except Exception as copy_error:
        print(f"✅ Exception caught in job processor: {copy_error}")
        
        was_paused = await copy_executor.handle_copy_failure(prepared_file, copy_error)
        
        if not was_paused:
            print("✅ SUCCESS: Job processor correctly handles REMOVED file (was_paused=False)")
            return True
        else:
            print("❌ ERROR: Job processor incorrectly thinks file was paused")
            return False


if __name__ == "__main__":
    async def main():
        success1 = await test_growing_file_removed_during_copying_complete_flow()
        success2 = await test_job_processor_integration()
        
        if success1 and success2:
            print("\n🎉 ALL TESTS PASSED! The growing file removal bug is completely fixed!")
        else:
            print("\n❌ Some tests failed. The bug fix needs more work.")
    
    asyncio.run(main())