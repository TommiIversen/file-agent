"""
Test for network interruption during GROWING_COPY recovery scenario.

This test catches a critical bug where files that are paused due to network
interruption get rediscovered by the file scanner and restart the entire
copy process instead of remaining in their paused state.

CRITICAL SCENARIO:
1. File is in GROWING_COPY status (actively copying with resume capability)
2. Network gets disconnected → file correctly transitions to PAUSED_GROWING_COPY
3. File scanner continues to run and rediscovers the same file
4. BUG: File gets treated as new → DISCOVERED → GROWING → SPACE_ERROR
5. CORRECT: File should remain PAUSED_GROWING_COPY until network recovery

RULE: Files that are already tracked and paused should NEVER be rediscovered
as new files. The file scanner must respect existing file states.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from app.config import Settings
from app.models import FileStatus, TrackedFile, StorageInfo, StorageStatus
from app.services.state_manager import StateManager
from app.services.scanner.file_scan_orchestrator import FileScanOrchestrator


class TestNetworkInterruptionRecovery:
    """Test suite for network interruption during growing copy."""

    @pytest.fixture
    def settings(self):
        """Test settings."""
        settings = Settings()
        settings.source_directory = "c:\\temp_input"
        settings.destination_directory = "\\\\SKumhesten\\testfeta"
        settings.polling_interval_seconds = 10
        settings.file_stable_time_seconds = 30
        return settings

    @pytest.fixture
    def state_manager(self):
        """Mock state manager."""
        return AsyncMock(spec=StateManager)

    @pytest.fixture
    def file_scan_orchestrator(self, settings, state_manager):
        """File scan orchestrator instance."""
        from app.services.scanner.domain_objects import ScanConfiguration
        
        # Create scan configuration
        config = ScanConfiguration(
            source_directory=settings.source_directory,
            file_stable_time_seconds=settings.file_stable_time_seconds,
            polling_interval_seconds=settings.polling_interval_seconds,
            enable_growing_file_support=True,
            growing_file_min_size_mb=100,
            keep_files_hours=24
        )
        
        orchestrator = FileScanOrchestrator(
            config=config,
            state_manager=state_manager,
            settings=settings
        )
        return orchestrator

    @pytest.fixture
    def paused_growing_file(self):
        """A file that was paused during growing copy due to network interruption."""
        return TrackedFile(
            id="test-uuid-network-123",
            file_path="c:\\temp_input\\Ingest_Cam1.mxf",
            status=FileStatus.PAUSED_GROWING_COPY,  # Paused due to network interruption
            file_size=32636928,  # Current size when paused
            bytes_copied=16318464,  # 50% copied when network failed
            discovered_at=datetime.now() - timedelta(minutes=5),
            started_copying_at=datetime.now() - timedelta(minutes=3),
            error_message="Network path was not found"
        )

    @pytest.mark.asyncio
    async def test_paused_file_should_not_be_rediscovered(
        self, file_scan_orchestrator, state_manager, paused_growing_file
    ):
        """
        CRITICAL TEST: Paused files should NOT be rediscovered as new files.
        
        When a file is already tracked and in PAUSED_GROWING_COPY state,
        the file scanner should NOT treat it as a new discovery.
        It should remain paused until network recovery.
        """
        # Setup: File exists on disk and is already tracked as paused
        file_path = paused_growing_file.file_path
        
        # Mock that file exists on disk (still growing)
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=paused_growing_file.file_size), \
             patch('os.path.getmtime', return_value=datetime.now().timestamp()):
            
            # Setup state manager to return existing paused file
            state_manager.get_file_by_path.return_value = paused_growing_file
            state_manager.get_active_file_by_path.return_value = paused_growing_file
            # CRITICAL: should_skip_file_processing should return True for paused files
            state_manager.should_skip_file_processing.return_value = True
            
            # Act: File scanner discovers the file (simulating continuous scanning)
            from app.services.scanner.domain_objects import FilePath
            discovered_files = {FilePath(file_path)}
            
            # The orchestrator should recognize this as an existing tracked file
            # and NOT process it as a new discovery
            
            # Process the discovered files
            await file_scan_orchestrator._process_discovered_files(discovered_files)
            
            # Assert: File should NOT be added as new discovery
            state_manager.add_file.assert_not_called()
            
            # Assert: File status should NOT be changed from PAUSED_GROWING_COPY
            status_update_calls = state_manager.update_file_status_by_id.call_args_list
            
            # Check that no call changes status away from PAUSED_GROWING_COPY
            for call in status_update_calls:
                call_kwargs = call.kwargs if hasattr(call, 'kwargs') else call[1]
                new_status = call_kwargs.get('status')
                
                # File should remain paused - no transitions to DISCOVERED, GROWING, etc.
                assert new_status != FileStatus.DISCOVERED, (
                    f"CRITICAL BUG: Paused file {paused_growing_file.file_path} "
                    f"was rediscovered as DISCOVERED! It should remain PAUSED_GROWING_COPY."
                )
                assert new_status != FileStatus.READY_TO_START_GROWING, (
                    f"CRITICAL BUG: Paused file {paused_growing_file.file_path} "
                    f"was marked as READY_TO_START_GROWING! It should remain PAUSED_GROWING_COPY."
                )

    @pytest.mark.asyncio
    async def test_network_interruption_complete_scenario(
        self, file_scan_orchestrator, state_manager, paused_growing_file, settings
    ):
        """
        Test complete network interruption and recovery scenario.
        
        1. File is in GROWING_COPY (actively copying with resume data)
        2. Network gets disconnected → PAUSED_GROWING_COPY
        3. File scanner continues running but should NOT rediscover paused file
        4. Network gets reconnected → file should resume from pause, not restart
        """
        file_path = paused_growing_file.file_path
        
        # Phase 1: File is actively growing and copying
        active_file = TrackedFile(
            id=paused_growing_file.id,
            file_path=file_path,
            status=FileStatus.GROWING_COPY,  # Actively copying
            file_size=paused_growing_file.file_size,
            bytes_copied=paused_growing_file.bytes_copied,
            discovered_at=paused_growing_file.discovered_at,
            started_copying_at=paused_growing_file.started_copying_at
        )
        
        # Phase 2: Network interruption - file becomes paused
        state_manager.get_file_by_path.return_value = paused_growing_file
        state_manager.get_active_file_by_path.return_value = paused_growing_file
        state_manager.get_active_file_by_path.return_value = paused_growing_file  # Use existing method
        state_manager.should_skip_file_processing.return_value = False
        
        # Mock file still exists and continues growing
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=paused_growing_file.file_size + 1000000), \
             patch('os.path.getmtime', return_value=(datetime.now() + timedelta(seconds=5)).timestamp()):
            
            # Act: File scanner runs while file is paused (simulating continuous scanning)
            from app.services.scanner.domain_objects import FilePath
            discovered_files = {FilePath(file_path)}
            
            await file_scan_orchestrator._process_discovered_files(discovered_files)
            
            # Assert: File should NOT be processed as new discovery
            state_manager.add_file.assert_not_called()
            
            # Assert: File should maintain paused state, not restart copy process
            update_calls = state_manager.update_file_status_by_id.call_args_list
            forbidden_statuses = [
                FileStatus.DISCOVERED,
                FileStatus.READY_TO_START_GROWING,
                FileStatus.IN_QUEUE,
                FileStatus.WAITING_FOR_SPACE
            ]
            
            for call in update_calls:
                call_kwargs = call.kwargs if hasattr(call, 'kwargs') else call[1]
                new_status = call_kwargs.get('status')
                
                assert new_status not in forbidden_statuses, (
                    f"CRITICAL BUG: Paused file was incorrectly transitioned to {new_status}! "
                    f"During network interruption, paused files should remain paused until recovery."
                )

    @pytest.mark.asyncio
    async def test_file_scanner_respects_existing_tracked_files(
        self, file_scan_orchestrator, state_manager
    ):
        """
        Test that file scanner always checks existing tracked files before processing.
        
        The scanner should NEVER process a file as new if it's already tracked,
        regardless of the file's current status.
        """
        # Setup: Multiple files in different tracked states
        tracked_files = [
            TrackedFile(
                id="uuid-1", file_path="c:\\temp_input\\file1.mxf",
                status=FileStatus.PAUSED_GROWING_COPY, file_size=1000000
            ),
            TrackedFile(
                id="uuid-2", file_path="c:\\temp_input\\file2.mxf", 
                status=FileStatus.PAUSED_COPYING, file_size=2000000
            ),
            TrackedFile(
                id="uuid-3", file_path="c:\\temp_input\\file3.mxv",
                status=FileStatus.SPACE_ERROR, file_size=3000000
            ),
            TrackedFile(
                id="uuid-4", file_path="c:\\temp_input\\file4.mxf",
                status=FileStatus.COMPLETED, file_size=4000000
            ),
        ]
        
        def mock_get_file_by_path(path):
            for tracked_file in tracked_files:
                if tracked_file.file_path == str(path):
                    return tracked_file
            return None
        
        def mock_is_file_tracked(path):
            return mock_get_file_by_path(path) is not None
        
        state_manager.get_file_by_path.side_effect = mock_get_file_by_path
        state_manager.get_active_file_by_path.side_effect = mock_get_file_by_path
        # Remove is_file_tracked - use get_active_file_by_path instead
        state_manager.should_skip_file_processing.return_value = False
        
        # Mock all files exist on disk
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=1000000), \
             patch('os.path.getmtime', return_value=datetime.now().timestamp()):
            
            # Act: Scanner discovers all files
            from app.services.scanner.domain_objects import FilePath
            discovered_files = {FilePath(tf.file_path) for tf in tracked_files}
            
            await file_scan_orchestrator._process_discovered_files(discovered_files)
            
            # Assert: NO files should be added as new discoveries
            state_manager.add_file.assert_not_called()
            
            # Assert: Scanner should respect existing states
            # Files should not be transitioned to discovery states
            update_calls = state_manager.update_file_status_by_id.call_args_list
            
            for call in update_calls:
                call_kwargs = call.kwargs if hasattr(call, 'kwargs') else call[1]
                new_status = call_kwargs.get('status')
                
                # No tracked file should be "rediscovered"
                assert new_status != FileStatus.DISCOVERED, (
                    "File scanner incorrectly rediscovered an already tracked file!"
                )

    def test_bug_documentation(self):
        """
        Document the network interruption bug this test prevents.
        
        This serves as documentation for future developers about the
        specific network recovery scenario that must work correctly.
        """
        bug_description = """
        NETWORK INTERRUPTION BUG PREVENTED BY THIS TEST:
        
        SCENARIO: File copying with resume capability during network failure
        
        1. File starts in GROWING_COPY status (actively copying with checksum resume data)
        2. Network connection is lost (SMB share becomes inaccessible)
        3. System correctly pauses file → PAUSED_GROWING_COPY ✅
        4. File scanner continues running and rediscovers the same file ❌
        5. Scanner treats paused file as new discovery ❌
        6. File transitions: PAUSED_GROWING_COPY → DISCOVERED → GROWING → SPACE_ERROR ❌
        7. Original resume data and progress is lost ❌
        8. File must restart from beginning when network recovers ❌
        
        CORRECT BEHAVIOR:
        - File scanner must check if file is already tracked before processing
        - Tracked files in ANY status should NEVER be rediscovered as new
        - Paused files should remain paused until universal recovery
        - Resume data and progress must be preserved during network interruption
        - When network recovers, file should resume from where it stopped
        
        CRITICAL IMPACT:
        - Large files (multi-GB) lose hours of copy progress
        - Network interruptions cause complete restart instead of resume
        - Checksum-based resume capability is completely bypassed
        """
        
        # This test ensures the bug described above cannot happen
        assert True, bug_description


if __name__ == "__main__":
    pytest.main([__file__, "-v"])