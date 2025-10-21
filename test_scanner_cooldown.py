#!/usr/bin/env python3
"""
Test that file scanner respects SPACE_ERROR cooldown.
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

from app.models import TrackedFile, FileStatus
from app.services.state_manager import StateManager


async def test_file_scanner_cooldown_logic():
    """Test that file scanner properly skips files in cooldown."""
    
    print("=== Testing File Scanner Cooldown Logic ===")
    
    # Create StateManager with 1 minute cooldown
    state_manager = StateManager(cooldown_minutes=1)
    
    # Create a file with SPACE_ERROR status and recent timestamp (should be in cooldown)
    recent_space_error_file = TrackedFile(
        id="recent-space-error",
        file_path="test_file.mxf",
        file_size=1000000,
        status=FileStatus.SPACE_ERROR,
        space_error_at=datetime.now() - timedelta(seconds=30)  # 30 seconds ago
    )
    
    # Add file to state manager
    state_manager._files_by_id[recent_space_error_file.id] = recent_space_error_file
    
    # Test should_skip_file_processing
    should_skip = await state_manager.should_skip_file_processing("test_file.mxf")
    print(f"Should skip file processing: {should_skip}")
    
    # Test get_active_file_by_path (this should still return the file)
    active_file = await state_manager.get_active_file_by_path("test_file.mxf") 
    print(f"get_active_file_by_path returns file: {active_file is not None}")
    
    # Create old file (should not be skipped)
    old_space_error_file = TrackedFile(
        id="old-space-error",
        file_path="old_test_file.mxf",
        file_size=1000000,
        status=FileStatus.SPACE_ERROR,
        space_error_at=datetime.now() - timedelta(minutes=2)  # 2 minutes ago
    )
    
    state_manager._files_by_id[old_space_error_file.id] = old_space_error_file
    
    should_skip_old = await state_manager.should_skip_file_processing("old_test_file.mxf")
    print(f"Should skip old file processing: {should_skip_old}")
    
    # Verify results
    success = True
    
    if not should_skip:
        print("❌ ERROR: Recent SPACE_ERROR file should be skipped")
        success = False
    else:
        print("✅ SUCCESS: Recent SPACE_ERROR file properly skipped")
    
    if active_file is None:
        print("❌ ERROR: get_active_file_by_path should still return the file")
        success = False 
    else:
        print("✅ SUCCESS: get_active_file_by_path returns file (for size updates etc)")
    
    if should_skip_old:
        print("❌ ERROR: Old SPACE_ERROR file should not be skipped")
        success = False
    else:
        print("✅ SUCCESS: Old SPACE_ERROR file not skipped (cooldown expired)")
    
    return success


if __name__ == "__main__":
    async def main():
        success = await test_file_scanner_cooldown_logic()
        if success:
            print("\n🎉 File scanner cooldown logic works correctly!")
        else:
            print("\n❌ File scanner cooldown logic has issues!")
    
    asyncio.run(main())