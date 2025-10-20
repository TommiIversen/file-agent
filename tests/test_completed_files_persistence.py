"""
Test for Completed Files Persistence
====================================

Tester at completed files bliver bevaret i memory efter page refresh
og ikke fjernes af cleanup processen.
"""

import asyncio
import tempfile
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.services.state_manager import StateManager
from app.services.scanner.file_scanner_service import FileScannerService
from app.models import FileStatus
from app.config import Settings


class TestCompletedFilesPersistence:
    """Test completed files persistence in memory"""

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
            file_stable_time_seconds=1,
            polling_interval_seconds=1,
            keep_completed_files_hours=2,  # Short for testing
            max_completed_files_in_memory=10,
        )

    @pytest.fixture
    def file_scanner(self, state_manager, test_settings):
        """Create FileScannerService for testing"""
        scanner = FileScannerService(test_settings, state_manager)
        yield scanner
        scanner.stop_scanning()

    @pytest.mark.asyncio
    async def test_completed_files_survive_cleanup(self, state_manager, temp_directory):
        """
        Test at COMPLETED filer ikke fjernes af cleanup selvom source filen er slettet.

        Scenarie:
        1. Tilføj en fil og marker som COMPLETED
        2. Slet source filen (simulerer normal copy workflow)
        3. Kør cleanup_missing_files
        4. Verify at COMPLETED filen stadig er i memory
        """
        # Create test file
        test_file = Path(temp_directory) / "completed_file.mxf"
        test_file.write_text("Test content")

        # Add file to state manager
        tracked_file = await state_manager.add_file(
            file_path=str(test_file), file_size=test_file.stat().st_size
        )

        # Mark as completed
        await state_manager.update_file_status_by_id(
            tracked_file.id, FileStatus.COMPLETED
        )

        # Verify file is completed
        completed_files = await state_manager.get_files_by_status(FileStatus.COMPLETED)
        assert len(completed_files) == 1
        assert completed_files[0].id == tracked_file.id

        # Delete source file (simulates normal copy workflow)
        test_file.unlink()

        # Run cleanup with empty existing_paths (no files exist)
        removed_count = await state_manager.cleanup_missing_files(set())

        # Verify completed file was NOT removed
        assert removed_count == 0, "Completed files should not be removed by cleanup"

        completed_files = await state_manager.get_files_by_status(FileStatus.COMPLETED)
        assert len(completed_files) == 1
        assert completed_files[0].id == tracked_file.id
        assert completed_files[0].status == FileStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_non_completed_files_removed_by_cleanup(
        self, state_manager, temp_directory
    ):
        """
        Test at ikke-completed filer stadig fjernes af cleanup når source er slettet.
        """
        # Create test file
        test_file = Path(temp_directory) / "discovered_file.mxf"
        test_file.write_text("Test content")

        # Add file as DISCOVERED
        tracked_file = await state_manager.add_file(
            file_path=str(test_file), file_size=test_file.stat().st_size
        )

        # Verify file is tracked
        all_files = await state_manager.get_all_files()
        assert len(all_files) == 1
        assert all_files[0].status == FileStatus.DISCOVERED

        # Delete source file
        test_file.unlink()

        # Run cleanup
        removed_count = await state_manager.cleanup_missing_files(set())

        # Verify non-completed file WAS removed
        assert removed_count == 1, "Non-completed files should be removed by cleanup"

        all_files = await state_manager.get_all_files()
        # Instead of expecting zero files, check that the file is marked as REMOVED
        assert len(all_files) == 1
        assert all_files[0].id == tracked_file.id
        assert all_files[0].status == FileStatus.REMOVED

    @pytest.mark.asyncio
    async def test_mixed_files_cleanup_behavior(self, state_manager, temp_directory):
        """
        Test cleanup behavior med både completed og non-completed filer.
        """
        # Create files
        completed_file = Path(temp_directory) / "completed.mxf"
        discovered_file = Path(temp_directory) / "discovered.mxf"
        existing_file = Path(temp_directory) / "existing.mxf"

        for file in [completed_file, discovered_file, existing_file]:
            file.write_text("Test content")

        # Add files to state manager
        tracked_completed = await state_manager.add_file(str(completed_file), 100)
        tracked_discovered = await state_manager.add_file(str(discovered_file), 100)
        tracked_existing = await state_manager.add_file(str(existing_file), 100)

        # Mark one as completed
        await state_manager.update_file_status_by_id(
            tracked_completed.id, FileStatus.COMPLETED
        )

        # Delete completed and discovered files (but keep existing file)
        completed_file.unlink()
        discovered_file.unlink()

        # Run cleanup with only existing file
        existing_paths = {str(existing_file)}
        removed_count = await state_manager.cleanup_missing_files(existing_paths)

        # Should remove only the discovered file (not completed, not existing)
        assert removed_count == 1

        all_files = await state_manager.get_all_files()
        # There should be 3 files: completed, existing, and discovered (now REMOVED)
        assert len(all_files) == 3

        # Verify completed file survived
        completed_files = await state_manager.get_files_by_status(FileStatus.COMPLETED)
        assert len(completed_files) == 1
        assert completed_files[0].id == tracked_completed.id

        # Verify existing file survived
        discovered_files = await state_manager.get_files_by_status(
            FileStatus.DISCOVERED
        )
        assert len(discovered_files) == 1
        assert discovered_files[0].id == tracked_existing.id

        # Verify discovered file is now REMOVED
        removed_files = await state_manager.get_files_by_status(FileStatus.REMOVED)
        assert len(removed_files) == 1
        assert removed_files[0].id == tracked_discovered.id

    @pytest.mark.asyncio
    async def test_old_completed_files_cleanup(self, state_manager):
        """
        Test at gamle completed filer fjernes efter konfigurabel tid.
        """
        # Create old completed file
        tracked_old = await state_manager.add_file("/old/file.mxf", 100)
        await state_manager.update_file_status_by_id(
            tracked_old.id, FileStatus.COMPLETED
        )

        # Manually set completion time to 3 hours ago
        old_completed_time = datetime.now() - timedelta(hours=3)

        async with state_manager._lock:
            tracked_file = state_manager._get_current_file_for_path("/old/file.mxf")
            if tracked_file:
                tracked_file.completed_at = old_completed_time

        # Create recent completed file
        tracked_recent = await state_manager.add_file("/recent/file.mxf", 100)
        await state_manager.update_file_status_by_id(
            tracked_recent.id, FileStatus.COMPLETED
        )

        # Run cleanup with 2 hour max age
        removed_count = await state_manager.cleanup_old_files(
            max_age_hours=2
        )

        # Should remove old file but keep recent one
        assert removed_count == 1

        all_files = await state_manager.get_all_files()
        assert len(all_files) == 1
        assert all_files[0].id == tracked_recent.id

    @pytest.mark.asyncio
    async def test_simple_age_based_cleanup(self, state_manager):
        """
        Test simple age-based cleanup of all files.
        """
        from datetime import datetime, timedelta
        
        # Create files with different completion times
        tracked_files = []
        for i in range(3):
            file_path = f"/test/file_{i}.mxf"
            tracked = await state_manager.add_file(file_path, 100)
            await state_manager.update_file_status_by_id(
                tracked.id, FileStatus.COMPLETED
            )
            
            # Make some files old
            if i < 2:  # First 2 files are old
                tracked.completed_at = datetime.now() - timedelta(hours=25)
            # Last file is recent (current time)
            
            tracked_files.append(tracked)

        # Run cleanup with 24 hour cutoff
        removed_count = await state_manager.cleanup_old_files(
            max_age_hours=24
        )

        # Should remove 2 old files, keep 1 recent
        assert removed_count == 2

        completed_files = await state_manager.get_files_by_status(FileStatus.COMPLETED)
        assert len(completed_files) == 1

        # Verify the recent file was kept
        assert completed_files[0].id == tracked_files[2].id

    @pytest.mark.asyncio
    async def test_completed_files_api_persistence(self, state_manager, temp_directory):
        """
        Test at completed files er tilgængelige via API efter page refresh simulation.
        """
        # Add completed file
        test_file = Path(temp_directory) / "api_test.mxf"
        test_file.write_text("API test content")

        tracked_file = await state_manager.add_file(
            str(test_file), test_file.stat().st_size
        )
        await state_manager.update_file_status_by_id(
            tracked_file.id, FileStatus.COMPLETED
        )

        # Delete source file (simulates copy completion)
        test_file.unlink()

        # Simulate file scanner cleanup (what happens during normal operation)
        await state_manager.cleanup_missing_files(set())

        # Verify completed file is still available via API methods
        all_files = await state_manager.get_all_files()
        assert len(all_files) == 1
        assert all_files[0].id == tracked_file.id
        assert all_files[0].status == FileStatus.COMPLETED

        completed_files = await state_manager.get_files_by_status(FileStatus.COMPLETED)
        assert len(completed_files) == 1
        assert completed_files[0].id == tracked_file.id

        statistics = await state_manager.get_statistics()
        assert statistics["status_counts"]["Completed"] == 1


# Manual test for debugging
async def manual_test_completed_persistence():
    """Manual test for completed files persistence"""
    print("🧪 Manual Completed Files Persistence Test")
    print("=" * 50)

    with tempfile.TemporaryDirectory() as temp_dir:
        # Setup
        state_manager = StateManager()

        # Create and add test file
        test_file = Path(temp_dir) / "test_completed.mxf"
        test_file.write_text("Test file for completion")

        print(f"📁 Created test file: {test_file}")

        # Add to state manager
        tracked_file = await state_manager.add_file(
            str(test_file), test_file.stat().st_size
        )
        print(f"✅ Added to StateManager: {tracked_file.status}")

        # Mark as completed
        await state_manager.update_file_status_by_id(
            tracked_file.id, FileStatus.COMPLETED
        )

        completed_files = await state_manager.get_files_by_status(FileStatus.COMPLETED)
        print(f"🎯 Completed files before cleanup: {len(completed_files)}")

        # Delete source file (simulates normal workflow)
        test_file.unlink()
        print("🗑️ Deleted source file")

        # Run cleanup (simulates what happens during scanning)
        removed_count = await state_manager.cleanup_missing_files(set())
        print(f"🧹 Cleanup removed: {removed_count} files")

        # Check if completed file survived
        completed_files = await state_manager.get_files_by_status(FileStatus.COMPLETED)
        print(f"✨ Completed files after cleanup: {len(completed_files)}")

        if completed_files:
            print(f"🎉 SUCCESS: Completed file persisted: {completed_files[0].id}")
        else:
            print("❌ FAILED: Completed file was removed")

    print("🏁 Manual test completed")


if __name__ == "__main__":
    asyncio.run(manual_test_completed_persistence())
