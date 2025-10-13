"""
Test Universal Recovery System

Test script til at verificere at growing files automatisk resumes efter
destination problems (network offline, disk full, mount failures, etc.)
"""

import asyncio
import tempfile
from pathlib import Path

# Test imports
from app.config import Settings  
from app.models import FileStatus, StorageStatus, TrackedFile
from app.services.state_manager import StateManager
from app.services.job_queue import JobQueueService
from app.services.storage_checker import StorageChecker
from app.services.storage_monitor import StorageMonitorService
from app.logging_config import setup_logging


async def test_universal_recovery():
    """Test universelt recovery system for alle destination problemer."""
    print("🧪 TESTING UNIVERSAL RECOVERY SYSTEM")
    print("=" * 60)
    
    # Configure settings first
    settings = Settings()
    
    # Setup logging
    setup_logging(settings)
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create test environment
        source_path = Path(temp_dir) / "source"
        dest_path = Path(temp_dir) / "dest"
        source_path.mkdir()
        dest_path.mkdir()
        
        settings.source_directory = str(source_path)
        settings.destination_directory = str(dest_path)
        settings.storage_check_interval_seconds = 1
        settings.enable_growing_file_support = True
        
        # Initialize services
        state_manager = StateManager()
        job_queue = JobQueueService(settings, state_manager)
        storage_checker = StorageChecker()
        storage_monitor = StorageMonitorService(
            settings=settings,
            storage_checker=storage_checker,
            job_queue=job_queue  # Enable universal recovery
        )
        
        print("✅ Services initialized")
        
        # Test 1: Add some failed files to state
        print("\n📂 Test 1: Setup failed and interrupted files")
        
        test_files = [
            ("failed_growing_1.mxf", FileStatus.FAILED, True),   # Failed growing file
            ("failed_normal_1.mp4", FileStatus.FAILED, False),   # Failed normal file  
            ("interrupted_1.mxf", FileStatus.COPYING, True),     # Interrupted growing
            ("interrupted_2.mp4", FileStatus.IN_QUEUE, False),   # Interrupted in queue
        ]
        
        for filename, status, is_growing in test_files:
            file_path = str(source_path / filename)
            
            # Add to state manager
            tracked_file = await state_manager.add_file(file_path, 1024*1024)  # 1MB
            await state_manager.update_file_status(
                file_path, 
                status,
                is_growing_file=is_growing,
                error_message="Simulated failure" if status == FileStatus.FAILED else None
            )
            
            print(f"  📄 Added: {filename} (status: {status}, growing: {is_growing})")
        
        # Verify initial state
        failed_files = await state_manager.get_failed_files()
        interrupted_files = await state_manager.get_interrupted_copy_files()
        growing_failed = await state_manager.get_failed_growing_files()
        
        print(f"\n📊 Initial State:")
        print(f"  - Total failed files: {len(failed_files)}")
        print(f"  - Total interrupted files: {len(interrupted_files)}")
        print(f"  - Failed growing files: {len(growing_failed)}")
        
        # Test 2: Simulate destination recovery
        print(f"\n🔄 Test 2: Simulating destination recovery")
        
        # Trigger recovery directly
        await job_queue.handle_destination_recovery()
        
        # Verify recovery results
        print(f"\n✅ Test 3: Verify recovery results")
        
        # Check that files were reset to READY
        recovered_count = 0
        for filename, original_status, is_growing in test_files:
            file_path = str(source_path / filename)
            tracked_file = await state_manager.get_file(file_path)
            
            if tracked_file and tracked_file.status == FileStatus.READY:
                recovered_count += 1
                print(f"  ✅ {filename}: {original_status} → READY (growing: {is_growing})")
            else:
                current_status = tracked_file.status if tracked_file else "NOT_FOUND"
                print(f"  ❌ {filename}: Expected READY, got {current_status}")
        
        print(f"\n📊 Recovery Results:")
        print(f"  - Files processed: {len(test_files)}")
        print(f"  - Successfully recovered: {recovered_count}")
        print(f"  - Recovery rate: {recovered_count/len(test_files)*100:.1f}%")
        
        # Test 4: Test storage monitor integration
        print(f"\n🔍 Test 4: Test storage monitor recovery detection")
        
        # Create mock storage infos
        from app.models import StorageInfo
        
        old_info = StorageInfo(
            path=str(dest_path),
            free_space_gb=10.0,
            total_space_gb=100.0,
            status=StorageStatus.ERROR,  # Problematic state
            is_accessible=False,
            has_write_access=False
        )
        
        new_info = StorageInfo(
            path=str(dest_path),
            free_space_gb=50.0,
            total_space_gb=100.0,
            status=StorageStatus.OK,  # Recovered state
            is_accessible=True,
            has_write_access=True
        )
        
        # Test recovery detection
        is_recovery = storage_monitor._is_destination_recovery("destination", old_info, new_info)
        print(f"  Recovery detected: {is_recovery} (ERROR → OK)")
        
        # Test non-recovery scenario
        same_info = StorageInfo(
            path=str(dest_path),
            free_space_gb=45.0,
            total_space_gb=100.0,
            status=StorageStatus.OK,
            is_accessible=True,
            has_write_access=True
        )
        
        is_not_recovery = storage_monitor._is_destination_recovery("destination", new_info, same_info)
        print(f"  Non-recovery detected: {is_not_recovery} (OK → OK)")
        
        print(f"\n🎉 UNIVERSAL RECOVERY TEST COMPLETE!")
        
        if recovered_count == len(test_files) and is_recovery and not is_not_recovery:
            print("✅ ALL TESTS PASSED!")
            return True
        else:
            print("❌ SOME TESTS FAILED!")
            return False


async def main():
    """Main test runner."""
    try:
        success = await test_universal_recovery()
        exit_code = 0 if success else 1
        
        print(f"\n{'='*60}")
        print(f"Test Result: {'PASS' if success else 'FAIL'}")
        print(f"Exit Code: {exit_code}")
        
        return exit_code
        
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    import sys
    exit_code = asyncio.run(main())
    sys.exit(exit_code)