"""
Test suite for Scanner UUID Integration.

Tests that verify scanner services work correctly with the new UUID-based
StateManager and benefit from automatic file history tracking.
"""

import pytest
from unittest.mock import Mock, patch

from app.models import FileStatus
from app.services.state_manager import StateManager
from app.services.scanner.domain_objects import ScanConfiguration
from app.config import Settings
from app.dependencies import reset_singletons

# Mark all tests as async
pytestmark = pytest.mark.asyncio


class TestScannerUUIDIntegration:
    """Test suite for Scanner services integration with UUID system."""

    @pytest.fixture
    def state_manager(self):
        """Fresh StateManager instance for each test."""
        reset_singletons()
        return StateManager()

    @pytest.fixture
    def scan_config(self):
        """Basic scan configuration for testing."""
        return ScanConfiguration(
            source_directory="/test/source",
            file_stable_time_seconds=2,
            polling_interval_seconds=5,
            keep_files_hours=336,
        )

    @pytest.fixture
    def mock_settings(self):
        """Mock Settings for testing."""
        settings = Mock(spec=Settings)
        settings.source_path = "/test/source"
        settings.destination_path = "/test/destination"
        settings.file_stable_time_seconds = 2
        return settings

    async def test_file_disappears_and_returns_creates_history(
        self, state_manager, scan_config, mock_settings
    ):
        """Test at en fil der forsvinder og kommer tilbage får korrekt historie tracking."""

        # file_id is now just a path, but all operations must use UUIDs
        file_path = "/test/source/video_001.mxf"

        # 1. Simulate file discovery - add file to StateManager
        tracked_file1 = await state_manager.add_file(file_path, 1024)
        assert tracked_file1.status == FileStatus.DISCOVERED
        assert tracked_file1.file_path == file_path
        original_uuid = tracked_file1.id

        # 2. Simulate file becomes ready
        await state_manager.update_file_status_by_id(tracked_file1.id, FileStatus.READY)

        # 4. Simulate file disappears (marked as REMOVED by cleanup)
        await state_manager.cleanup_missing_files(
            set()
        )  # Empty set = all files missing

        # Verify file is marked as REMOVED
        removed_file = await state_manager.get_file_by_id(tracked_file1.id)
        # Updated: The new implementation returns a TrackedFile with status=REMOVED, not None
        assert removed_file is not None
        assert removed_file.status == FileStatus.REMOVED


        # 5. Simulate same file returns (scanner discovers it again)
        tracked_file2 = await state_manager.add_file(file_path, 2048)  # Different size

        # Should create NEW entry with NEW UUID
        assert tracked_file2.status == FileStatus.DISCOVERED
        assert tracked_file2.file_path == file_path
        assert tracked_file2.file_size == 2048
        assert tracked_file2.id != original_uuid  # NEW UUID!


    async def test_scanner_handles_existing_removed_files(
        self, state_manager, scan_config, mock_settings
    ):
        """Test at scanner korrekt håndterer filer der allerede er REMOVED."""

        # file_path = "/test/source/video_002.mxf"
        file_id = "/test/source/video_002.mxf"

        # 1. Add file and mark as REMOVED (simulate previous cycle)
        tracked_file1 = await state_manager.add_file(file_id, 1024)
        await state_manager.update_file_status_by_id(
            tracked_file1.id, FileStatus.READY
        )  # Not COMPLETED, so it can be REMOVED
        await state_manager.cleanup_missing_files(set())  # Mark as REMOVED

        # 2. Simulate scanner discovers same file again (mocking the discovery logic)
        existing_file = await state_manager.get_file_by_id(tracked_file1.id)
        # Updated: The new implementation returns a file with REMOVED status, not None
        assert existing_file is not None
        assert existing_file.status == FileStatus.REMOVED

        # 3. Scanner should add it as new file (this is what happens in real code)
        tracked_file2 = await state_manager.add_file(file_id, 1500)

        # Should get new file with new UUID
        assert tracked_file2.status == FileStatus.DISCOVERED
        assert tracked_file2.file_size == 1500
        assert tracked_file2.id != tracked_file1.id


        current_file = await state_manager.get_file_by_id(tracked_file2.id)
        assert current_file is not None
        assert current_file.id == tracked_file2.id

    async def test_scanner_multiple_files_same_name_over_time(
        self, state_manager, scan_config, mock_settings
    ):
        """Test scenario hvor samme fil kommer og går flere gange."""

        file_id = "/test/source/temp_render.mxf"

        # Simulate multiple cycles of same filename
        file_uuids = []

        for cycle in range(3):
            # 1. File appears
            tracked_file = await state_manager.add_file(file_id, 1000 + cycle * 100)
            file_uuids.append(tracked_file.id)

            # 2. File processed (but not COMPLETED so it can be marked REMOVED)
            await state_manager.update_file_status_by_id(
                tracked_file.id, FileStatus.READY
            )
            await state_manager.update_file_status_by_id(
                tracked_file.id, FileStatus.COPYING
            )

            # 3. File disappears (back to READY state so cleanup can mark as REMOVED)
            await state_manager.update_file_status_by_id(
                tracked_file.id, FileStatus.READY
            )
            await state_manager.cleanup_missing_files(set())


    async def test_uuid_based_file_updates_work_with_scanner(
        self, state_manager, scan_config, mock_settings
    ):
        """Test at de nye UUID-baserede APIs virker sammen med scanner workflow."""

        file_id = "/test/source/video_003.mxf"

        # 1. Scanner adds file
        tracked_file = await state_manager.add_file(file_id, 2048)
        original_uuid = tracked_file.id

        # 2. Use UUID-based update (new method)
        await state_manager.update_file_status_by_id(tracked_file.id, FileStatus.READY)

        # 3. Use UUID-based update with progress (demonstration)
        result = await state_manager.update_file_status_by_id(
            original_uuid, FileStatus.COPYING, copy_progress=25.0
        )

        assert result is not None
        assert result.status == FileStatus.COPYING
        assert result.copy_progress == 25.0
        assert result.id == original_uuid

        # 4. Verify both methods updated same file
        current_file = await state_manager.get_file_by_path(file_id)
        assert current_file.id == original_uuid
        assert current_file.status == FileStatus.COPYING
        assert current_file.copy_progress == 25.0

        # 5. Verify by ID lookup works
        by_id_file = await state_manager.get_file_by_id(original_uuid)
        assert by_id_file.id == original_uuid
        assert by_id_file.file_path == file_id
        assert by_id_file.status == FileStatus.COPYING

    async def test_scanner_benefits_from_automatic_history_logging(
        self, state_manager, scan_config, mock_settings
    ):
        """Test at scanner automatisk får benefit af historie logging."""

        file_id = "/test/source/project_final.mxf"

        # Simulate realistic scanner workflow med historie
        with patch("app.services.state_manager.logging") as mock_logging:
            # 1. Initial discovery
            tracked_file1 = await state_manager.add_file(file_id, 5000)

            # 2. File disappears
            await state_manager.cleanup_missing_files(set())

            # 3. File returns
            tracked_file2 = await state_manager.add_file(file_id, 5000)

            # Verify correct logging happened
            mock_logging.info.assert_any_call(
                f"File returned after REMOVED - creating new entry: {file_id}"
            )

            # Should also log preservation of history
            assert any(
                "Previous REMOVED entry preserved as history" in str(call)
                for call in mock_logging.info.call_args_list
            )

        # Verify two distinct entries exist
        assert tracked_file1.id != tracked_file2.id


    async def test_file_lifecycle_cleanup(self, state_manager):
        # Add file and mark as READY
        tracked_file = await state_manager.add_file("/test/file1.mxf", 100)
        await state_manager.update_file_status_by_id(tracked_file.id, FileStatus.READY)
        # Remove file (simulate missing)
        removed_count = await state_manager.cleanup_missing_files(set())
        assert removed_count == 1
        all_files = await state_manager.get_all_files()
        assert all_files[0].status == FileStatus.REMOVED

    async def test_status_update_by_id(self, state_manager):
        tracked_file = await state_manager.add_file("/test/file2.mxf", 100)
        await state_manager.update_file_status_by_id(
            tracked_file.id, FileStatus.COPYING
        )
        file = await state_manager.get_file_by_id(tracked_file.id)
        assert file.status == FileStatus.COPYING

    async def test_cleanup_removes_only_non_completed(self, state_manager):
        completed = await state_manager.add_file("/test/comp.mxf", 100)
        await state_manager.add_file("/test/disc.mxf", 100)
        await state_manager.update_file_status_by_id(completed.id, FileStatus.COMPLETED)
        removed_count = await state_manager.cleanup_missing_files(set())
        assert removed_count == 1
        all_files = await state_manager.get_all_files()
        statuses = {f.status for f in all_files}
        assert FileStatus.COMPLETED in statuses
        assert FileStatus.REMOVED in statuses

    async def test_cleanup_old_files_by_age(self, state_manager):
        completed = await state_manager.add_file("/test/old.mxf", 100)
        await state_manager.update_file_status_by_id(completed.id, FileStatus.COMPLETED)
        # Simulate old completion
        from datetime import datetime, timedelta

        # Get file reference OUTSIDE the lock, then modify it
        file = await state_manager.get_file_by_id(completed.id)
        if file:
            # Now manually set the completed_at time without holding the lock
            file.completed_at = datetime.now() - timedelta(hours=3)

        # Add recent
        recent = await state_manager.add_file("/test/recent.mxf", 100)
        await state_manager.update_file_status_by_id(recent.id, FileStatus.COMPLETED)
        removed_count = await state_manager.cleanup_old_files(max_age_hours=2)
        assert removed_count == 1
        all_files = await state_manager.get_all_files()
        assert all_files[0].id == recent.id
