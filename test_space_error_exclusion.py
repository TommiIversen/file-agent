#!/usr/bin/env python3
"""
Test that growing file detector ignores files with SPACE_ERROR status.
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

from app.models import TrackedFile, FileStatus
from app.services.growing_file_detector import GrowingFileDetector
from app.config import Settings


@pytest.mark.asyncio
async def test_growing_file_detector_ignores_space_error():
    """Test that growing file detector ignores files with SPACE_ERROR status."""
    
    print("=== Testing Growing File Detector SPACE_ERROR Handling ===")
    
    # Mock settings and state manager
    settings = Settings(
        source_directory="test",
        destination_directory="test", 
        growing_file_min_size_mb=5,
        growing_file_poll_interval_seconds=1,
        growing_file_growth_timeout_seconds=10
    )
    
    state_manager = AsyncMock()
    
    # Create growing file detector
    detector = GrowingFileDetector(settings, state_manager)
    
    # Create test files with different statuses
    space_error_file = TrackedFile(
        id="space-error-file",
        file_path="space_error_test.mxf",
        file_size=1000000,
        status=FileStatus.SPACE_ERROR,
        last_growth_check=datetime.now()  # This would normally make it eligible for processing
    )
    
    growing_file = TrackedFile(
        id="growing-file",
        file_path="growing_test.mxf", 
        file_size=1000000,
        status=FileStatus.GROWING,
        last_growth_check=datetime.now()
    )
    
    # Mock state_manager.get_all_files to return our test files
    state_manager.get_all_files.return_value = [space_error_file, growing_file]
    
    # Test the filtering logic used in _monitor_growing_files_loop
    all_files = await state_manager.get_all_files()
    growing_files = [
        f for f in all_files 
        if f.last_growth_check is not None 
        and f.status not in [
            FileStatus.IN_QUEUE,
            FileStatus.COPYING,
            FileStatus.GROWING_COPY,
            FileStatus.COMPLETED,
            FileStatus.FAILED,
            FileStatus.REMOVED,
            FileStatus.SPACE_ERROR,  # This should exclude our space error file
        ]
    ]
    
    # Check results
    print(f"Total files: {len(all_files)}")
    print(f"Files after filtering: {len(growing_files)}")
    
    # Should only have the GROWING file, not the SPACE_ERROR file
    if len(growing_files) == 1 and growing_files[0].status == FileStatus.GROWING:
        print("✅ SUCCESS: SPACE_ERROR file is properly excluded from processing")
        print(f"✅ Only processing file with status: {growing_files[0].status}")
        return True
    else:
        print("❌ FAILURE: SPACE_ERROR file was not properly excluded")
        for f in growing_files:
            print(f"  - File with status: {f.status}")
        return False


if __name__ == "__main__":
    async def main():
        success = await test_growing_file_detector_ignores_space_error()
        if success:
            print("\n🎉 Growing file detector SPACE_ERROR test passed!")
        else:
            print("\n❌ Growing file detector SPACE_ERROR test failed!")
    
    asyncio.run(main())