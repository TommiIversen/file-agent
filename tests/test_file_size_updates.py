"""
Test for File Size Updates During Discovery Phase
================================================================

Dette test verificerer at file_size opdateres korrekt i UI mens
filer er i DISCOVERED state og stadig vokser.
"""

import asyncio
import tempfile
import os
from pathlib import Path

import pytest

from app.services.state_manager import StateManager
from app.services.file_scanner import FileScannerService
from app.models import FileStatus
from app.config import Settings


class TestFileSizeUpdates:
    """Test file size updates during discovery phase"""
    
    @pytest.fixture
    def state_manager(self):
        """Create StateManager instance for testing"""
        return StateManager()
    
    @pytest.fixture
    def temp_directory(self):
        """Create temporary directory for test files"""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield temp_dir
    
    @pytest.fixture
    def test_settings(self, temp_directory):
        """Create test settings with temporary directories"""
        return Settings(
            source_directory=temp_directory,
            destination_directory=os.path.join(temp_directory, "dest"),
            file_stable_time_seconds=2,  # Short for testing
            polling_interval_seconds=1
        )
    
    @pytest.fixture
    def file_scanner(self, state_manager, test_settings):
        """Create FileScannerService for testing"""
        scanner = FileScannerService(test_settings, state_manager)
        yield scanner
        # Cleanup
        scanner.stop_scanning()
    
    @pytest.mark.asyncio
    async def test_file_size_updates_during_discovery(
        self, 
        file_scanner, 
        state_manager, 
        temp_directory
    ):
        """
        Test at file_size opdateres mens filen er i DISCOVERED state.
        
        Scenarie:
        1. Opret en fil med initial size
        2. Fil bliver opdaget og får DISCOVERED status
        3. Fil vokser (simuleret ved at tilføje mere indhold)
        4. Verify at file_size opdateres i TrackedFile
        """
        # Create test file
        test_file = Path(temp_directory) / "growing_file.mxf"
        
        # Step 1: Write initial content
        initial_content = "Initial content for MXF file"
        test_file.write_text(initial_content)
        initial_size = test_file.stat().st_size
        
        # Step 2: Run file discovery
        discovered_files = await file_scanner._discover_files()
        await file_scanner._process_discovered_files(discovered_files)
        
        # Verify file was discovered
        discovered_files = await state_manager.get_files_by_status(FileStatus.DISCOVERED)
        assert len(discovered_files) == 1
        
        tracked_file = discovered_files[0]
        assert tracked_file.file_path == str(test_file)
        assert tracked_file.file_size == initial_size
        assert tracked_file.status == FileStatus.DISCOVERED
        
        # Step 3: Simulate file growth
        additional_content = "\nAdditional content added to file - this makes it grow!"
        with open(test_file, 'a') as f:
            f.write(additional_content)
        
        new_size = test_file.stat().st_size
        assert new_size > initial_size, "File should have grown"
        
        # Step 4: Run stability check (which should detect size change)
        await file_scanner._check_file_stability()
        
        # Step 5: Verify file_size was updated
        updated_files = await state_manager.get_files_by_status(FileStatus.DISCOVERED)
        assert len(updated_files) == 1
        
        updated_tracked_file = updated_files[0]
        assert updated_tracked_file.file_path == str(test_file)
        assert updated_tracked_file.file_size == new_size, (
            f"File size should be updated from {initial_size} to {new_size}, "
            f"but was {updated_tracked_file.file_size}"
        )
        assert updated_tracked_file.status == FileStatus.DISCOVERED
    
    @pytest.mark.asyncio
    async def test_file_size_multiple_updates(
        self, 
        file_scanner, 
        state_manager, 
        temp_directory
    ):
        """
        Test multiple file size updates som filen vokser gradvist.
        """
        test_file = Path(temp_directory) / "multi_growth.mxf"
        
        # Initial file
        test_file.write_text("Start")
        initial_size = test_file.stat().st_size
        
        # Discover file
        discovered_files = await file_scanner._discover_files()
        await file_scanner._process_discovered_files(discovered_files)
        
        tracked_file = (await state_manager.get_files_by_status(FileStatus.DISCOVERED))[0]
        assert tracked_file.file_size == initial_size
        
        # Growth iteration 1
        with open(test_file, 'a') as f:
            f.write(" -> Growth 1")
        
        await file_scanner._check_file_stability()
        
        tracked_file = (await state_manager.get_files_by_status(FileStatus.DISCOVERED))[0]
        size_after_growth_1 = test_file.stat().st_size
        assert tracked_file.file_size == size_after_growth_1
        assert size_after_growth_1 > initial_size
        
        # Growth iteration 2
        with open(test_file, 'a') as f:
            f.write(" -> Growth 2")
        
        await file_scanner._check_file_stability()
        
        tracked_file = (await state_manager.get_files_by_status(FileStatus.DISCOVERED))[0]
        size_after_growth_2 = test_file.stat().st_size
        assert tracked_file.file_size == size_after_growth_2
        assert size_after_growth_2 > size_after_growth_1
    
    @pytest.mark.asyncio
    async def test_no_size_update_when_file_stable(
        self, 
        file_scanner, 
        state_manager, 
        temp_directory
    ):
        """
        Test at file_size ikke opdateres unødvendigt når filen er stabil.
        """
        test_file = Path(temp_directory) / "stable_file.mxf"
        test_file.write_text("Stable content")
        
        # Discover file
        discovered_files = await file_scanner._discover_files()
        await file_scanner._process_discovered_files(discovered_files)
        
        # Wait for stability period
        await asyncio.sleep(3)  # More than file_stable_time_seconds
        
        # Check stability (should promote to READY, not update size)
        await file_scanner._check_file_stability()
        
        # File should be promoted to READY
        ready_files = await state_manager.get_files_by_status(FileStatus.READY)
        assert len(ready_files) == 1
        
        discovered_files = await state_manager.get_files_by_status(FileStatus.DISCOVERED)
        assert len(discovered_files) == 0
    
    @pytest.mark.asyncio
    async def test_size_update_with_websocket_notification(
        self, 
        file_scanner, 
        state_manager, 
        temp_directory
    ):
        """
        Test at size updates trigger websocket notifications for UI.
        """
        notifications = []
        
        # Subscribe to state updates
        async def capture_notifications(update):
            notifications.append(update)
        
        state_manager.subscribe(capture_notifications)
        
        # Create and grow file
        test_file = Path(temp_directory) / "notification_test.mxf"
        test_file.write_text("Initial")
        
        # Discover file
        discovered_files = await file_scanner._discover_files()
        await file_scanner._process_discovered_files(discovered_files)
        
        initial_notifications = len(notifications)
        
        # Grow file
        with open(test_file, 'a') as f:
            f.write(" -> Grown")
        
        # Trigger update
        await file_scanner._check_file_stability()
        
        # Should have received notification for size update
        assert len(notifications) > initial_notifications
        
        # Find the size update notification
        size_update_notifications = [
            n for n in notifications[initial_notifications:] 
            if n.new_status == FileStatus.DISCOVERED and 
               n.old_status == FileStatus.DISCOVERED
        ]
        
        assert len(size_update_notifications) >= 1, (
            "Should receive notification when file size is updated"
        )


# Manual test script for debugging
async def manual_test_file_growth():
    """Manual test script for testing file growth simulation"""
    print("🧪 Manual File Growth Test")
    print("=" * 40)
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Setup
        settings = Settings(
            source_directory=temp_dir,
            destination_directory=os.path.join(temp_dir, "dest"),
            file_stable_time_seconds=3,
            polling_interval_seconds=1
        )
        
        state_manager = StateManager()
        file_scanner = FileScannerService(settings, state_manager)
        
        # Create growing file
        test_file = Path(temp_dir) / "test_growth.mxf"
        print(f"📁 Created test file: {test_file}")
        
        try:
            # Initial content
            test_file.write_text("Initial MXF content")
            initial_size = test_file.stat().st_size
            print(f"📏 Initial size: {initial_size} bytes")
            
            # Discover file
            discovered_files = await file_scanner._discover_files()
            await file_scanner._process_discovered_files(discovered_files)
            discovered = await state_manager.get_files_by_status(FileStatus.DISCOVERED)
            
            if discovered:
                print(f"✅ File discovered: {discovered[0].file_size} bytes")
                
                # Simulate growth
                for i in range(3):
                    await asyncio.sleep(1)
                    
                    # Add content
                    with open(test_file, 'a') as f:
                        f.write(f"\nGrowth iteration {i+1} - adding more content to simulate file growth!")
                    
                    new_size = test_file.stat().st_size
                    print(f"📈 Growth {i+1}: {new_size} bytes (+{new_size - initial_size})")
                    
                    # Check for updates
                    await file_scanner._check_file_stability()
                    
                    updated = await state_manager.get_files_by_status(FileStatus.DISCOVERED)
                    if updated:
                        print(f"🔄 Tracked size: {updated[0].file_size} bytes")
                    else:
                        ready = await state_manager.get_files_by_status(FileStatus.READY)
                        if ready:
                            print(f"✅ File promoted to READY: {ready[0].file_size} bytes")
                            break
            
        finally:
            file_scanner.stop_scanning()
    
    print("🏁 Manual test completed")


if __name__ == "__main__":
    # Run manual test
    asyncio.run(manual_test_file_growth())