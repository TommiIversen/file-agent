"""
Integration test for FileStabilityTracker removal.

This test verifies that FileScanOrchestrator correctly uses StateManager
for file stability tracking instead of the removed FileStabilityTracker.
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timedelta
from pathlib import Path

from app.services.scanner.file_scanner import FileScanner
from app.services.scanner.domain_objects import ScanConfiguration
from app.services.state_manager import StateManager
from app.models import FileStatus
from app.dependencies import reset_singletons
from app.config import Settings


@pytest.mark.asyncio
class TestFileStabilityRefactoring:
    """Test suite verifying FileStabilityTracker removal and StateManager integration."""

    @pytest.fixture
    def state_manager(self):
        """Fresh StateManager instance for each test."""
        reset_singletons()
        from app.core.file_repository import FileRepository
        file_repository = FileRepository()
        return StateManager(file_repository=file_repository)

    @pytest.fixture
    def scan_config(self):
        """Basic scan configuration for testing."""
        return ScanConfiguration(
            source_directory="/test/source",
            file_stable_time_seconds=2,  # Short for tests
            polling_interval_seconds=5,
            keep_files_hours=336,
        )

    @pytest.fixture
    def orchestrator(self, scan_config, state_manager):
        """FileScanOrchestrator instance for testing."""
        settings = MagicMock(spec=Settings)
        settings.growing_file_min_size_mb = 100
        settings.growing_file_poll_interval_seconds = 5
        settings.growing_file_safety_margin_mb = 50
        settings.growing_file_growth_timeout_seconds = 300
        settings.growing_file_chunk_size_kb = 2048
        return FileScanner(
            config=scan_config,
            state_manager=state_manager,
            storage_monitor=None,
            settings=settings,
        )

    @pytest.mark.skip(
        reason="Test is outdated - new architecture uses growing file logic for all files"
    )
    async def test_file_changes_reset_stability_timer(
        self, orchestrator, state_manager
    ):
        """Test that file changes reset the stability timer via StateManager."""

        # Create a tracked file
        file_path = "/test/source/video.mxf"
        original_time = datetime.now() - timedelta(seconds=10)
        tracked_file = await state_manager.add_file(
            file_path, 1024, last_write_time=original_time
        )
        await state_manager.update_file_status_by_id(
            tracked_file.id, FileStatus.DISCOVERED
        )

        # Store original discovered_at
        original_discovered = tracked_file.discovered_at

        # Create metadata dictionary with changed size
        new_time = datetime.now()
        metadata = {
            "path": Path(file_path),
            "size": 2048,  # Different size
            "last_write_time": new_time,
        }

        # Call stability logic
        with patch(
            "app.services.scanner.file_scanner.get_file_metadata",
            new_callable=AsyncMock,
        ) as mock_get_metadata:
            mock_get_metadata.return_value = metadata
            # Mock the state manager's get_files_by_status to return our file
            with patch.object(
                state_manager, "get_files_by_status", new_callable=AsyncMock
            ) as mock_get_files:
                mock_get_files.return_value = [tracked_file]
                # We need to simulate that the _handle_growing_file_logic method actually calls the growing detector
                with patch.object(
                    orchestrator.growing_file_detector,
                    "update_file_growth_info",
                    new_callable=AsyncMock,
                ):
                    with patch.object(
                        orchestrator.growing_file_detector,
                        "check_file_growth_status",
                        new_callable=AsyncMock,
                    ) as mock_check_growth:
                        # Return the same status to prevent any status change
                        mock_check_growth.return_value = (FileStatus.DISCOVERED, None)
                        await orchestrator._check_file_stability()

        # Verify file metadata was updated and timer reset
        updated_file = await state_manager.get_file_by_id(tracked_file.id)
        assert updated_file.file_size == 2048
        assert updated_file.last_write_time == new_time
        assert updated_file.discovered_at > original_discovered  # Timer was reset

    @pytest.mark.skip(
        reason="Test is outdated - new architecture uses growing file logic for all files"
    )
    async def test_stable_file_transitions_to_ready(self, orchestrator, state_manager):
        """Test that stable files transition to READY status."""

        # Create a tracked file and make it "old" enough to be stable
        file_path = "/test/source/video.mxf"
        write_time = datetime.now() - timedelta(seconds=5)
        tracked_file = await state_manager.add_file(
            file_path, 1024, last_write_time=write_time
        )
        await state_manager.update_file_status_by_id(
            tracked_file.id, FileStatus.DISCOVERED
        )

        # Manually set discovered_at to simulate stability period
        await state_manager.update_file_status_by_id(
            tracked_file.id,
            FileStatus.DISCOVERED,
            discovered_at=datetime.now() - timedelta(seconds=3),
        )

        # Create metadata dictionary (no changes)
        metadata = {
            "path": Path(file_path),
            "size": 1024,
            "last_write_time": write_time,
        }

        # Call stability logic
        with patch(
            "app.services.scanner.file_scanner.get_file_metadata",
            new_callable=AsyncMock,
        ) as mock_get_metadata:
            mock_get_metadata.return_value = metadata
            # Mock the state manager's get_files_by_status to return our file
            with patch.object(
                state_manager, "get_files_by_status", new_callable=AsyncMock
            ) as mock_get_files:
                mock_get_files.return_value = [tracked_file]
                # We need to simulate the growing file detector behavior
                with patch.object(
                    orchestrator.growing_file_detector,
                    "update_file_growth_info",
                    new_callable=AsyncMock,
                ):
                    with patch.object(
                        orchestrator.growing_file_detector,
                        "check_file_growth_status",
                        new_callable=AsyncMock,
                    ) as mock_check_growth:
                        # Return READY status to simulate file is ready
                        mock_check_growth.return_value = (FileStatus.READY, None)
                        await orchestrator._check_file_stability()

        # Verify file transitioned to READY
        updated_file = await state_manager.get_file_by_id(tracked_file.id)
        assert updated_file.status == FileStatus.READY

    async def test_no_file_stability_tracker_instance(self, orchestrator):
        # Verify FileStabilityTracker is not present
        assert not hasattr(orchestrator, "stability_tracker")
        assert hasattr(orchestrator, "state_manager")
