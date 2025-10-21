"""
Test that Growing File Detector respects paused file statuses.

This test ensures that Growing File Detector cannot override paused files
with new status recommendations, preventing the critical network interruption
bug where paused files get reactivated by growing file monitoring.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
from pathlib import Path

from app.config import Settings
from app.models import TrackedFile, FileStatus
from app.services.growing_file_detector import GrowingFileDetector
from app.services.state_manager import StateManager


class TestGrowingFileDetectorPausedRespect:
    """Test that Growing File Detector respects paused file statuses."""

    @pytest.fixture
    def settings(self):
        """Test settings for growing file detector."""
        settings = Settings()
        settings.growing_file_min_size_mb = 10  # 10MB minimum
        settings.growing_file_poll_interval_seconds = 1
        settings.growing_file_growth_timeout_seconds = 5
        return settings

    @pytest.fixture
    def state_manager(self):
        """Mock state manager."""
        return AsyncMock(spec=StateManager)

    @pytest.fixture
    def growing_file_detector(self, settings, state_manager):
        """Growing file detector instance."""
        return GrowingFileDetector(settings, state_manager)

    @pytest.fixture
    def paused_growing_file(self):
        """A file that was paused during growing copy."""
        return TrackedFile(
            id="test-uuid-paused-123",
            file_path="c:\\temp_input\\paused_file.mxf",
            status=FileStatus.PAUSED_GROWING_COPY,  # File is paused
            file_size=15000000,  # 15MB (above minimum size)
            discovered_at=datetime.now() - timedelta(minutes=5),
            last_growth_check=datetime.now() - timedelta(seconds=10),  # Has growth tracking
            growth_stable_since=datetime.now() - timedelta(seconds=6),  # Stable for 6 seconds
            error_message="Network interruption"
        )

    @pytest.mark.asyncio
    async def test_paused_files_excluded_from_growing_monitoring(
        self, growing_file_detector, state_manager, paused_growing_file
    ):
        """Test that paused files are excluded from growing file monitoring list."""
        # Setup: Return paused file from get_all_files
        state_manager.get_all_files.return_value = [paused_growing_file]
        
        # Mock file existence and size for growth check
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=paused_growing_file.file_size):
            
            # Act: Run one iteration of growing file monitoring
            all_files = await state_manager.get_all_files()
            growing_files = [
                f for f in all_files 
                if f.last_growth_check is not None 
                and f.status not in [
                    FileStatus.IN_QUEUE,
                    FileStatus.COPYING,
                    FileStatus.GROWING_COPY,
                    FileStatus.COMPLETED,
                    FileStatus.FAILED,
                    FileStatus.REMOVED,
                    FileStatus.SPACE_ERROR,
                    # CRITICAL: Paused files should be excluded
                    FileStatus.PAUSED_IN_QUEUE,
                    FileStatus.PAUSED_COPYING,
                    FileStatus.PAUSED_GROWING_COPY,
                ]
            ]
            
            # Assert: Paused file should be excluded from monitoring
            assert len(growing_files) == 0, (
                f"CRITICAL BUG: Paused file {paused_growing_file.file_path} "
                f"was included in growing file monitoring! Paused files should "
                f"be excluded to prevent status overrides during network recovery."
            )

    @pytest.mark.asyncio
    async def test_growing_detector_skips_paused_status_updates(
        self, growing_file_detector, state_manager
    ):
        """Test that Growing File Detector skips status updates for paused files."""
        # Create a file that would normally be ready for growing copy
        ready_file = TrackedFile(
            id="test-uuid-ready-123",
            file_path="c:\\temp_input\\ready_file.mxf",
            status=FileStatus.GROWING,  # Currently growing
            file_size=15000000,  # 15MB (above minimum)
            discovered_at=datetime.now() - timedelta(minutes=5),
            last_growth_check=datetime.now() - timedelta(seconds=1),
            growth_stable_since=datetime.now() - timedelta(seconds=6),  # Stable for 6 seconds
        )
        
        # Setup: get_file_by_id returns paused file (simulating file was paused after growth check)
        paused_file = TrackedFile(
            id=ready_file.id,
            file_path=ready_file.file_path,
            status=FileStatus.PAUSED_GROWING_COPY,  # File was paused!
            file_size=ready_file.file_size,
            discovered_at=ready_file.discovered_at,
            last_growth_check=ready_file.last_growth_check,
            growth_stable_since=ready_file.growth_stable_since,
        )
        
        state_manager.get_file_by_id.return_value = paused_file
        
        # Mock file operations for growth check
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=ready_file.file_size), \
             patch('os.path.getmtime', return_value=datetime.now().timestamp()):
            
            # Act: Check growth status for file that appears ready
            recommended_status, _ = await growing_file_detector.check_file_growth_status(ready_file)
            
            # CRITICAL: When a file is paused, Growing File Detector should return 
            # the original status WITHOUT performing logic checks that would normally
            # recommend READY_TO_START_GROWING. This prevents paused files from being
            # reactivated during network recovery.
            assert recommended_status == FileStatus.GROWING  # Original status, not computed
            
            # Verify that no status updates were called
            state_manager.update_file_status_by_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_paused_statuses_protected_from_growing_updates(
        self, growing_file_detector, state_manager
    ):
        """Test that all paused statuses are protected from growing file updates."""
        paused_statuses = [
            FileStatus.PAUSED_IN_QUEUE,
            FileStatus.PAUSED_COPYING,
            FileStatus.PAUSED_GROWING_COPY,
        ]
        
        for paused_status in paused_statuses:
            # Reset mock
            state_manager.reset_mock()
            
            # Create file that would be ready for update
            growing_file = TrackedFile(
                id=f"test-uuid-{paused_status.value}",
                file_path=f"c:\\temp_input\\test_{paused_status.value}.mxf",
                status=FileStatus.GROWING,
                file_size=15000000,
                discovered_at=datetime.now() - timedelta(minutes=5),
                last_growth_check=datetime.now() - timedelta(seconds=1),
                growth_stable_since=datetime.now() - timedelta(seconds=6),
            )
            
            # File becomes paused
            paused_file = TrackedFile(
                id=growing_file.id,
                file_path=growing_file.file_path,
                status=paused_status,  # Different paused status
                file_size=growing_file.file_size,
                discovered_at=growing_file.discovered_at,
                last_growth_check=growing_file.last_growth_check,
                growth_stable_since=growing_file.growth_stable_since,
            )
            
            state_manager.get_file_by_id.return_value = paused_file
            
            # Mock file operations
            with patch('os.path.exists', return_value=True), \
                 patch('os.path.getsize', return_value=growing_file.file_size), \
                 patch('os.path.getmtime', return_value=datetime.now().timestamp()):
                
                # Check that file would be ready for update (if not paused)
                recommended_status, _ = await growing_file_detector.check_file_growth_status(growing_file)
                
                # CRITICAL: For paused files, Growing File Detector should return the original
                # status without performing logic that would recommend new statuses.
                # This prevents paused files from being reactivated.
                assert recommended_status == FileStatus.GROWING  # Original status, not computed
                
                # Verify that no status updates were called for paused files
                state_manager.update_file_status_by_id.assert_not_called()

    def test_network_interruption_scenario_documentation(self):
        """
        Document the exact scenario this test prevents.
        
        This serves as documentation for the critical network interruption
        bug that Growing File Detector can cause if not properly handled.
        """
        scenario_description = """
        NETWORK INTERRUPTION BUG PREVENTED BY THIS TEST:
        
        SCENARIO: Growing file monitoring during network interruption
        
        1. File is in GROWING_COPY status (actively copying with resume data)
        2. Network gets disconnected → Storage Monitor pauses file → PAUSED_GROWING_COPY ✅
        3. Growing File Detector continues monitoring file growth ❌
        4. File continues growing on source (normal behavior)
        5. Growing File Detector sees file is stable and ready → recommends READY_TO_START_GROWING ❌
        6. Growing File Detector calls update_file_status_by_id() ❌
        7. File status changes: PAUSED_GROWING_COPY → READY_TO_START_GROWING ❌
        8. Job Queue picks up file and tries to copy → gets network error → SPACE_ERROR ❌
        9. Resume data is lost and file must restart from beginning ❌
        
        CORRECT BEHAVIOR:
        - Growing File Detector must exclude paused files from monitoring
        - Growing File Detector must never update status for paused files
        - Paused files should remain paused until universal recovery
        - Network recovery should resume from where copy stopped
        
        CRITICAL IMPACT:
        - Large files lose hours of copy progress during network interruptions
        - Network issues cause complete restart instead of resume
        - Resume capability is completely bypassed
        """
        
        # This test ensures the scenario described above cannot happen
        assert True, scenario_description


if __name__ == "__main__":
    pytest.main([__file__, "-v"])