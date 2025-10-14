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
            enable_growing_file_support=False,
            growing_file_min_size_mb=100,
            keep_completed_files_hours=24,
            max_completed_files_in_memory=1000,
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
        
        # Note: We're testing StateManager behavior that scanner would use
        # The orchestrator itself is not directly tested here
        
        file_path = "/test/source/video_001.mxf"
        
        # 1. Simulate file discovery - add file to StateManager
        tracked_file1 = await state_manager.add_file(file_path, 1024)
        assert tracked_file1.status == FileStatus.DISCOVERED
        assert tracked_file1.file_path == file_path
        original_uuid = tracked_file1.id
        
        # 2. Simulate file becomes ready
        await state_manager.update_file_status_by_id(tracked_file1.id, FileStatus.READY)
        
        # 3. Simulate file becomes READY (not completed, so it can be marked as REMOVED) - redundant, removing
        
        # 4. Simulate file disappears (marked as REMOVED by cleanup)
        await state_manager.cleanup_missing_files(set())  # Empty set = all files missing
        
        # Verify file is marked as REMOVED
        removed_file = await state_manager.get_file(file_path)
        assert removed_file is None  # get_file excludes REMOVED files
        
        # But history should exist
        history = await state_manager.get_file_history(file_path)
        assert len(history) == 1
        assert history[0].status == FileStatus.REMOVED
        assert history[0].id == original_uuid
        
        # 5. Simulate same file returns (scanner discovers it again)
        tracked_file2 = await state_manager.add_file(file_path, 2048)  # Different size
        
        # Should create NEW entry with NEW UUID
        assert tracked_file2.status == FileStatus.DISCOVERED
        assert tracked_file2.file_path == file_path
        assert tracked_file2.file_size == 2048
        assert tracked_file2.id != original_uuid  # NEW UUID!
        
        # 6. Verify we now have history
        history = await state_manager.get_file_history(file_path)
        assert len(history) == 2
        
        # Most recent first (sorted by discovered_at descending)
        current_entry = history[0]
        removed_entry = history[1]
        
        assert current_entry.id == tracked_file2.id
        assert current_entry.status == FileStatus.DISCOVERED
        assert current_entry.file_size == 2048
        
        assert removed_entry.id == original_uuid
        assert removed_entry.status == FileStatus.REMOVED
        assert removed_entry.file_size == 1024

    async def test_scanner_handles_existing_removed_files(
        self, state_manager, scan_config, mock_settings
    ):
        """Test at scanner korrekt håndterer filer der allerede er REMOVED."""
        
        file_path = "/test/source/video_002.mxf"
        
        # 1. Add file and mark as REMOVED (simulate previous cycle)
        tracked_file1 = await state_manager.add_file(file_path, 1024)
        await state_manager.update_file_status_by_id(tracked_file1.id, FileStatus.READY)  # Not COMPLETED, so it can be REMOVED
        await state_manager.cleanup_missing_files(set())  # Mark as REMOVED
        
        # 2. Simulate scanner discovers same file again (mocking the discovery logic)
        existing_file = await state_manager.get_file(file_path)
        assert existing_file is None  # Should not find REMOVED files
        
        # 3. Scanner should add it as new file (this is what happens in real code)
        tracked_file2 = await state_manager.add_file(file_path, 1500)
        
        # Should get new file with new UUID
        assert tracked_file2.status == FileStatus.DISCOVERED
        assert tracked_file2.file_size == 1500
        assert tracked_file2.id != tracked_file1.id
        
        # 4. Verify history preserved
        history = await state_manager.get_file_history(file_path)
        assert len(history) == 2
        
        current_file = await state_manager.get_file(file_path)
        assert current_file is not None
        assert current_file.id == tracked_file2.id

    async def test_scanner_multiple_files_same_name_over_time(
        self, state_manager, scan_config, mock_settings
    ):
        """Test scenario hvor samme fil kommer og går flere gange."""
        
        file_path = "/test/source/temp_render.mxf"
        
        # Simulate multiple cycles of same filename
        file_uuids = []
        
        for cycle in range(3):
            # 1. File appears
            tracked_file = await state_manager.add_file(file_path, 1000 + cycle * 100)
            file_uuids.append(tracked_file.id)
            
            # 2. File processed (but not COMPLETED so it can be marked REMOVED)
            await state_manager.update_file_status_by_id(tracked_file.id, FileStatus.READY)
            await state_manager.update_file_status_by_id(tracked_file.id, FileStatus.COPYING)
            
            # 3. File disappears (back to READY state so cleanup can mark as REMOVED)
            await state_manager.update_file_status_by_id(tracked_file.id, FileStatus.READY)
            await state_manager.cleanup_missing_files(set())
            
        # Verify we have full history
        history = await state_manager.get_file_history(file_path)
        assert len(history) == 3
        
        # All should be REMOVED status now
        for entry in history:
            assert entry.status == FileStatus.REMOVED
        
        # All should have unique UUIDs
        history_uuids = [entry.id for entry in history]
        assert len(set(history_uuids)) == 3
        assert set(history_uuids) == set(file_uuids)
        
        # Different file sizes
        file_sizes = [entry.file_size for entry in history]
        expected_sizes = [1200, 1100, 1000]  # Most recent first
        assert file_sizes == expected_sizes

    async def test_uuid_based_file_updates_work_with_scanner(
        self, state_manager, scan_config, mock_settings
    ):
        """Test at de nye UUID-baserede APIs virker sammen med scanner workflow."""
        
        file_path = "/test/source/video_003.mxf"
        
        # 1. Scanner adds file
        tracked_file = await state_manager.add_file(file_path, 2048)
        original_uuid = tracked_file.id
        
        # 2. Use UUID-based update (new method)
        await state_manager.update_file_status_by_id(tracked_file.id, FileStatus.READY)
        
        # 3. Use UUID-based update with progress (demonstration)
        result = await state_manager.update_file_status_by_id(
            original_uuid, 
            FileStatus.COPYING,
            copy_progress=25.0
        )
        
        assert result is not None
        assert result.status == FileStatus.COPYING
        assert result.copy_progress == 25.0
        assert result.id == original_uuid
        
        # 4. Verify both methods updated same file
        current_file = await state_manager.get_file(file_path)
        assert current_file.id == original_uuid
        assert current_file.status == FileStatus.COPYING
        assert current_file.copy_progress == 25.0
        
        # 5. Verify by ID lookup works
        by_id_file = await state_manager.get_file_by_id(original_uuid)
        assert by_id_file.id == original_uuid
        assert by_id_file.file_path == file_path
        assert by_id_file.status == FileStatus.COPYING

    async def test_scanner_benefits_from_automatic_history_logging(
        self, state_manager, scan_config, mock_settings
    ):
        """Test at scanner automatisk får benefit af historie logging."""
        
        file_path = "/test/source/project_final.mxf"
        
        # Simulate realistic scanner workflow med historie
        with patch('app.services.state_manager.logging') as mock_logging:
            
            # 1. Initial discovery
            tracked_file1 = await state_manager.add_file(file_path, 5000)
            
            # 2. File disappears
            await state_manager.cleanup_missing_files(set())
            
            # 3. File returns
            tracked_file2 = await state_manager.add_file(file_path, 5000)
            
            # Verify correct logging happened
            mock_logging.info.assert_any_call(
                f"File returned after REMOVED - creating new entry: {file_path}"
            )
            
            # Should also log preservation of history
            assert any(
                "Previous REMOVED entry preserved as history" in str(call)
                for call in mock_logging.info.call_args_list
            )
        
        # Verify two distinct entries exist
        assert tracked_file1.id != tracked_file2.id
        
        # Verify history
        history = await state_manager.get_file_history(file_path)
        assert len(history) == 2