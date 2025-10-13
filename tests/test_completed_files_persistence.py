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
        await state_manager.add_file(
            file_path=str(test_file), file_size=test_file.stat().st_size
        )

        # Mark as completed
        await state_manager.update_file_status(
            file_path=str(test_file), status=FileStatus.COMPLETED
        )

        # Verify file is completed
        completed_files = await state_manager.get_files_by_status(FileStatus.COMPLETED)
        assert len(completed_files) == 1
        assert completed_files[0].file_path == str(test_file)

        # Delete source file (simulates normal copy workflow)
        test_file.unlink()

        # Run cleanup with empty existing_paths (no files exist)
        removed_count = await state_manager.cleanup_missing_files(set())

        # Verify completed file was NOT removed
        assert removed_count == 0, "Completed files should not be removed by cleanup"

        completed_files = await state_manager.get_files_by_status(FileStatus.COMPLETED)
        assert len(completed_files) == 1
        assert completed_files[0].file_path == str(test_file)
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
        await state_manager.add_file(
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
        assert len(all_files) == 0

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
        await state_manager.add_file(str(completed_file), 100)
        await state_manager.add_file(str(discovered_file), 100)
        await state_manager.add_file(str(existing_file), 100)

        # Mark one as completed
        await state_manager.update_file_status(
            str(completed_file), FileStatus.COMPLETED
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
        assert len(all_files) == 2  # completed + existing

        # Verify completed file survived
        completed_files = await state_manager.get_files_by_status(FileStatus.COMPLETED)
        assert len(completed_files) == 1
        assert completed_files[0].file_path == str(completed_file)

        # Verify existing file survived
        discovered_files = await state_manager.get_files_by_status(
            FileStatus.DISCOVERED
        )
        assert len(discovered_files) == 1
        assert discovered_files[0].file_path == str(existing_file)

    @pytest.mark.asyncio
    async def test_old_completed_files_cleanup(self, state_manager):
        """
        Test at gamle completed filer fjernes efter konfigurabel tid.
        """
        # Create old completed file
        await state_manager.add_file("/old/file.mxf", 100)
        await state_manager.update_file_status("/old/file.mxf", FileStatus.COMPLETED)

        # Manually set completion time to 3 hours ago
        old_completed_time = datetime.now() - timedelta(hours=3)

        async with state_manager._lock:
            state_manager._files["/old/file.mxf"].completed_at = old_completed_time

        # Create recent completed file
        await state_manager.add_file("/recent/file.mxf", 100)
        await state_manager.update_file_status("/recent/file.mxf", FileStatus.COMPLETED)

        # Run cleanup with 2 hour max age
        removed_count = await state_manager.cleanup_old_completed_files(
            max_age_hours=2, max_count=100
        )

        # Should remove old file but keep recent one
        assert removed_count == 1

        all_files = await state_manager.get_all_files()
        assert len(all_files) == 1
        assert all_files[0].file_path == "/recent/file.mxf"

    @pytest.mark.asyncio
    async def test_max_completed_files_limit(self, state_manager):
        """
        Test at max antal completed filer respekteres.
        """
        # Create 5 completed files
        for i in range(5):
            file_path = f"/test/file_{i}.mxf"
            await state_manager.add_file(file_path, 100)
            await state_manager.update_file_status(file_path, FileStatus.COMPLETED)

            # Slight delay to ensure different completion times
            await asyncio.sleep(0.01)

        # Run cleanup with max 3 files
        removed_count = await state_manager.cleanup_old_completed_files(
            max_age_hours=24,  # Don't remove by age
            max_count=3,
        )

        # Should remove 2 oldest files
        assert removed_count == 2

        completed_files = await state_manager.get_files_by_status(FileStatus.COMPLETED)
        assert len(completed_files) == 3

        # Verify newest files were kept
        file_paths = [f.file_path for f in completed_files]
        assert "/test/file_2.mxf" in file_paths
        assert "/test/file_3.mxf" in file_paths
        assert "/test/file_4.mxf" in file_paths

    @pytest.mark.asyncio
    async def test_completed_files_api_persistence(self, state_manager, temp_directory):
        """
        Test at completed files er tilgængelige via API efter page refresh simulation.
        """
        # Add completed file
        test_file = Path(temp_directory) / "api_test.mxf"
        test_file.write_text("API test content")

        await state_manager.add_file(str(test_file), test_file.stat().st_size)
        await state_manager.update_file_status(str(test_file), FileStatus.COMPLETED)

        # Delete source file (simulates copy completion)
        test_file.unlink()

        # Simulate file scanner cleanup (what happens during normal operation)
        await state_manager.cleanup_missing_files(set())

        # Verify completed file is still available via API methods
        all_files = await state_manager.get_all_files()
        assert len(all_files) == 1
        assert all_files[0].status == FileStatus.COMPLETED

        completed_files = await state_manager.get_files_by_status(FileStatus.COMPLETED)
        assert len(completed_files) == 1

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
        await state_manager.update_file_status(str(test_file), FileStatus.COMPLETED)

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
            print(
                f"🎉 SUCCESS: Completed file persisted: {completed_files[0].file_path}"
            )
        else:
            print("❌ FAILED: Completed file was removed")

    print("🏁 Manual test completed")


if __name__ == "__main__":
    asyncio.run(manual_test_completed_persistence())
