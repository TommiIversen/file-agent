"""
Integration test for FileStabilityTracker removal.

This test verifies that FileScanOrchestrator correctly uses StateManager
for file stability tracking instead of the removed FileStabilityTracker.
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timedelta

from app.services.scanner.file_scan_orchestrator import FileScanOrchestrator
from app.services.scanner.domain_objects import ScanConfiguration, FileMetadata, FilePath
from app.services.state_manager import StateManager
from app.models import FileStatus
from app.dependencies import reset_singletons


@pytest.mark.asyncio
class TestFileStabilityRefactoring:
    """Test suite verifying FileStabilityTracker removal and StateManager integration."""

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
            file_stable_time_seconds=2,  # Short for tests
            polling_interval_seconds=5,
            enable_growing_file_support=False,
            growing_file_min_size_mb=100,
            keep_files_hours=336,
        )

    @pytest.fixture
    def orchestrator(self, scan_config, state_manager):
        """FileScanOrchestrator instance for testing."""
        return FileScanOrchestrator(
            config=scan_config,
            state_manager=state_manager,
            storage_monitor=None,
            settings=None,
        )

    async def test_traditional_stability_logic_uses_state_manager(
        self, orchestrator, state_manager
    ):
        """Test that _handle_traditional_stability_logic uses StateManager for stability checks."""
        
        # Create a tracked file
        file_path = "/test/source/video.mxf"
        tracked_file = await state_manager.add_file(file_path, 1024)
        
        # Create metadata with same info (no changes)
        metadata = FileMetadata(
            path=FilePath(file_path),
            size=1024,
            last_write_time=tracked_file.last_write_time,
        )
        
        # Mock StateManager methods to verify they are called
        with patch.object(state_manager, 'update_file_metadata', new_callable=AsyncMock) as mock_update:
            with patch.object(state_manager, 'is_file_stable', new_callable=AsyncMock) as mock_stable:
                mock_update.return_value = False  # No changes
                mock_stable.return_value = True   # File is stable
                
                # Call the stability logic
                await orchestrator._handle_traditional_stability_logic(metadata, tracked_file)
                
                # Verify StateManager methods were called
                mock_update.assert_called_once_with(
                    tracked_file.id, 1024, tracked_file.last_write_time
                )
                mock_stable.assert_called_once_with(
                    tracked_file.id, orchestrator.config.file_stable_time_seconds
                )

    async def test_file_changes_reset_stability_timer(
        self, orchestrator, state_manager
    ):
        """Test that file changes reset the stability timer via StateManager."""
        
        # Create a tracked file
        file_path = "/test/source/video.mxf"
        original_time = datetime.now() - timedelta(seconds=10)
        tracked_file = await state_manager.add_file(file_path, 1024, last_write_time=original_time)
        
        # Store original discovered_at
        original_discovered = tracked_file.discovered_at
        
        # Create metadata with changed size
        new_time = datetime.now()
        metadata = FileMetadata(
            path=FilePath(file_path),
            size=2048,  # Different size
            last_write_time=new_time,
        )
        
        # Call stability logic
        await orchestrator._handle_traditional_stability_logic(metadata, tracked_file)
        
        # Verify file metadata was updated and timer reset
        updated_file = await state_manager.get_file_by_id(tracked_file.id)
        assert updated_file.file_size == 2048
        assert updated_file.last_write_time == new_time
        assert updated_file.discovered_at > original_discovered  # Timer was reset

    async def test_stable_file_transitions_to_ready(
        self, orchestrator, state_manager
    ):
        """Test that stable files transition to READY status."""
        
        # Create a tracked file and make it "old" enough to be stable
        file_path = "/test/source/video.mxf"
        write_time = datetime.now() - timedelta(seconds=5)
        tracked_file = await state_manager.add_file(file_path, 1024, last_write_time=write_time)
        
        # Manually set discovered_at to simulate stability period
        tracked_file.discovered_at = datetime.now() - timedelta(seconds=3)
        
        # Create metadata (no changes)
        metadata = FileMetadata(
            path=FilePath(file_path),
            size=1024,
            last_write_time=write_time,
        )
        
        # Call stability logic
        await orchestrator._handle_traditional_stability_logic(metadata, tracked_file)
        
        # Verify file transitioned to READY
        updated_file = await state_manager.get_file_by_id(tracked_file.id)
        assert updated_file.status == FileStatus.READY

    async def test_no_file_stability_tracker_instance(self, orchestrator):
        """Test that FileScanOrchestrator no longer has a FileStabilityTracker instance."""
        
        # Verify FileStabilityTracker is not present
        assert not hasattr(orchestrator, 'stability_tracker')
        
        # Verify required components are still present
        assert hasattr(orchestrator, 'state_manager')
        assert hasattr(orchestrator, 'cleanup_service')