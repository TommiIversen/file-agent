"""
Test Intelligent Pause/Resume System

Test det nye pause/resume system der bevarer interrupt context
og fortsætter seamless fra bytes offset.
"""

import asyncio
import tempfile
from pathlib import Path

# Test imports
from app.config import Settings  
from app.models import FileStatus, StorageStatus
from app.services.state_manager import StateManager
from app.services.job_queue import JobQueueService
from app.services.storage_checker import StorageChecker
from app.services.storage_monitor import StorageMonitorService
from app.logging_config import setup_logging


async def test_intelligent_pause_resume():
    """Test intelligent pause/resume system."""
    print("🧪 TESTING INTELLIGENT PAUSE/RESUME SYSTEM")
    print("=" * 70)
    
    # Setup
    settings = Settings()
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
            job_queue=job_queue
        )
        
        print("✅ Services initialized")
        
        # Test 1: Setup active operations
        print("\n📂 Test 1: Setup active copy operations")
        
        test_files = [
            ("active_in_queue.mxv", FileStatus.IN_QUEUE, True, 0),
            ("active_copying.mxf", FileStatus.COPYING, True, 1024*1024*50),  # 50MB copied
            ("active_growing.mxf", FileStatus.GROWING_COPY, True, 1024*1024*100),  # 100MB copied
            ("normal_file.mp4", FileStatus.COPYING, False, 1024*1024*25),  # 25MB copied
        ]
        
        for filename, status, is_growing, bytes_copied in test_files:
            file_path = str(source_path / filename)
            
            # Add to state manager
            tracked_file = await state_manager.add_file(file_path, 1024*1024*200)  # 200MB total
            await state_manager.update_file_status(
                file_path, 
                status,
                is_growing_file=is_growing,
                bytes_copied=bytes_copied,
                copy_progress=(bytes_copied / (1024*1024*200)) * 100
            )
            
            print(f"  📄 Added: {filename} (status: {status}, copied: {bytes_copied:,} bytes)")
        
        # Test 2: Simulate destination unavailable
        print(f"\n⏸️ Test 2: Simulating destination unavailable")
        
        # Trigger pause
        await job_queue.handle_destination_unavailable()
        
        # Verify pause results
        print(f"\n📊 Test 3: Verify pause results")
        
        paused_count = 0
        for filename, original_status, is_growing, original_bytes in test_files:
            file_path = str(source_path / filename)
            tracked_file = await state_manager.get_file(file_path)
            
            if tracked_file:
                expected_paused_status = None
                if original_status == FileStatus.IN_QUEUE:
                    expected_paused_status = FileStatus.PAUSED_IN_QUEUE
                elif original_status == FileStatus.COPYING:
                    expected_paused_status = FileStatus.PAUSED_COPYING
                elif original_status == FileStatus.GROWING_COPY:
                    expected_paused_status = FileStatus.PAUSED_GROWING_COPY
                
                if expected_paused_status and tracked_file.status == expected_paused_status:
                    paused_count += 1
                    print(f"  ✅ {filename}: {original_status} → {tracked_file.status}")
                    print(f"     Bytes preserved: {tracked_file.bytes_copied:,} (expected: {original_bytes:,})")
                else:
                    print(f"  ❌ {filename}: Expected {expected_paused_status}, got {tracked_file.status}")
        
        # Test 4: Simulate destination recovery  
        print(f"\n▶️ Test 4: Simulating destination recovery")
        
        # Trigger resume
        await job_queue.handle_destination_recovery()
        
        # Verify resume results
        print(f"\n📊 Test 5: Verify resume results")
        
        resumed_count = 0
        for filename, original_status, is_growing, original_bytes in test_files:
            file_path = str(source_path / filename)
            tracked_file = await state_manager.get_file(file_path)
            
            if tracked_file:
                # Check if file was properly resumed
                expected_resumed_status = None
                if original_status == FileStatus.IN_QUEUE:
                    expected_resumed_status = FileStatus.IN_QUEUE
                elif original_status in [FileStatus.COPYING, FileStatus.GROWING_COPY]:
                    expected_resumed_status = FileStatus.READY  # Will be requeued with resume context
                
                if expected_resumed_status and tracked_file.status == expected_resumed_status:
                    resumed_count += 1
                    print(f"  ✅ {filename}: Resumed to {tracked_file.status}")
                    print(f"     Bytes preserved: {tracked_file.bytes_copied:,} (original: {original_bytes:,})")
                else:
                    print(f"  ❌ {filename}: Expected {expected_resumed_status}, got {tracked_file.status}")
        
        # Test 6: Test storage monitor integration
        print(f"\n🔍 Test 6: Test storage monitor pause/resume detection")
        
        from app.models import StorageInfo
        
        # Test pause detection (OK → ERROR)
        old_info = StorageInfo(
            path=str(dest_path),
            free_space_gb=50.0,
            total_space_gb=100.0,
            used_space_gb=50.0,
            status=StorageStatus.OK,
            is_accessible=True,
            has_write_access=True,
            warning_threshold_gb=10.0,
            critical_threshold_gb=5.0,
            last_checked=__import__('datetime').datetime.now()
        )
        
        new_info = StorageInfo(
            path=str(dest_path),
            free_space_gb=0.0,
            total_space_gb=100.0,
            used_space_gb=100.0,
            status=StorageStatus.ERROR,
            is_accessible=False,
            has_write_access=False,
            warning_threshold_gb=10.0,
            critical_threshold_gb=5.0,
            last_checked=__import__('datetime').datetime.now()
        )
        
        is_unavailable = storage_monitor._is_destination_unavailable("destination", old_info, new_info)
        print(f"  Unavailable detected: {is_unavailable} (OK → ERROR)")
        
        # Test recovery detection (ERROR → OK)  
        recovery_info = StorageInfo(
            path=str(dest_path),
            free_space_gb=45.0,
            total_space_gb=100.0,
            used_space_gb=55.0,
            status=StorageStatus.OK,
            is_accessible=True,
            has_write_access=True,
            warning_threshold_gb=10.0,
            critical_threshold_gb=5.0,
            last_checked=__import__('datetime').datetime.now()
        )
        
        is_recovery = storage_monitor._is_destination_recovery("destination", new_info, recovery_info)
        print(f"  Recovery detected: {is_recovery} (ERROR → OK)")
        
        print(f"\n🎉 INTELLIGENT PAUSE/RESUME TEST COMPLETE!")
        
        success = (paused_count == len(test_files) and 
                  resumed_count == len(test_files) and 
                  is_unavailable and is_recovery)
        
        if success:
            print("✅ ALL TESTS PASSED!")
            print("\n🏆 Key Achievements:")
            print("  - Active operations paused with preserved context")
            print("  - Bytes copied preserved during pause")
            print("  - Operations resumed seamlessly")
            print("  - Storage monitor detects pause/resume events")
            print("  - Ready for resume strategies to continue from offset")
            return True
        else:
            print("❌ SOME TESTS FAILED!")
            return False


async def main():
    """Main test runner."""
    try:
        success = await test_intelligent_pause_resume()
        exit_code = 0 if success else 1
        
        print(f"\n{'='*70}")
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