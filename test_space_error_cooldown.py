#!/usr/bin/env python3
"""
Test SPACE_ERROR cooldown functionality.
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

from app.models import TrackedFile, FileStatus
from app.services.state_manager import StateManager


async def test_space_error_cooldown():
    """Test that SPACE_ERROR files respect cooldown period."""
    
    print("=== Testing SPACE_ERROR Cooldown Functionality ===")
    
    # Create StateManager
    state_manager = StateManager()
    
    # Create a file with SPACE_ERROR status and recent timestamp
    recent_space_error_file = TrackedFile(
        id="recent-space-error",
        file_path="test_file.mxf",
        file_size=1000000,
        status=FileStatus.SPACE_ERROR,
        space_error_at=datetime.now() - timedelta(minutes=30)  # 30 minutes ago
    )
    
    # Create a file with SPACE_ERROR status and old timestamp 
    old_space_error_file = TrackedFile(
        id="old-space-error",
        file_path="test_file_old.mxf", 
        file_size=1000000,
        status=FileStatus.SPACE_ERROR,
        space_error_at=datetime.now() - timedelta(minutes=90)  # 90 minutes ago
    )
    
    # Add files to state manager manually for testing
    state_manager._files_by_id[recent_space_error_file.id] = recent_space_error_file
    state_manager._files_by_id[old_space_error_file.id] = old_space_error_file
    
    # Test cooldown check
    print("Testing cooldown detection...")
    
    # Recent file should be in cooldown (default 60 minutes)
    is_recent_in_cooldown = state_manager._is_space_error_in_cooldown(recent_space_error_file)
    print(f"Recent file (30 min ago) in cooldown: {is_recent_in_cooldown}")
    
    # Old file should not be in cooldown
    is_old_in_cooldown = state_manager._is_space_error_in_cooldown(old_space_error_file)
    print(f"Old file (90 min ago) in cooldown: {is_old_in_cooldown}")
    
    # Test get_active_file_by_path respects cooldown
    print("\nTesting get_active_file_by_path...")
    
    recent_result = await state_manager.get_active_file_by_path("test_file.mxf")
    old_result = await state_manager.get_active_file_by_path("test_file_old.mxf")
    
    print(f"Recent file returned by get_active_file_by_path: {recent_result is not None}")
    print(f"Old file returned by get_active_file_by_path: {old_result is not None}")
    
    # Verify results
    success = True
    
    if not is_recent_in_cooldown:
        print("❌ ERROR: Recent file should be in cooldown")
        success = False
    else:
        print("✅ SUCCESS: Recent file properly detected as in cooldown")
    
    if is_old_in_cooldown:
        print("❌ ERROR: Old file should not be in cooldown")
        success = False
    else:
        print("✅ SUCCESS: Old file properly detected as out of cooldown")
    
    if recent_result is not None:
        print("❌ ERROR: Recent file should not be returned due to cooldown")
        success = False
    else:
        print("✅ SUCCESS: Recent file properly excluded due to cooldown")
    
    if old_result is None:
        print("❌ ERROR: Old file should be returned (out of cooldown)")
        success = False
    else:
        print("✅ SUCCESS: Old file properly returned (out of cooldown)")
    
    return success


if __name__ == "__main__":
    async def main():
        success = await test_space_error_cooldown()
        if success:
            print("\n🎉 SPACE_ERROR cooldown functionality works correctly!")
        else:
            print("\n❌ SPACE_ERROR cooldown functionality has issues!")
    
    asyncio.run(main())