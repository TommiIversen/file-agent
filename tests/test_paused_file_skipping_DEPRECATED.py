"""
Test should_skip_file_processing for paused files.

This test ensures that file scanner skips processing of paused files,
preventing the critical network interruption bug where paused files
get rediscovered and restart their copy process.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

from app.models import TrackedFile, FileStatus
from app.services.state_manager import StateManager


class TestPausedFileSkipping:
    """Test that paused files are properly skipped by file scanner."""

    @pytest.mark.asyncio
    async def test_should_skip_paused_growing_copy_files(self):
        """Test that PAUSED_GROWING_COPY files are skipped by scanner."""
        state_manager = StateManager(AsyncMock())
        
        # Create a paused growing copy file
        paused_file = TrackedFile(
            id="test-uuid-123",
            file_path="c:\\temp_input\\test_file.mxf",
            status=FileStatus.PAUSED_GROWING_COPY,
            file_size=1000000,
            discovered_at=datetime.now()
        )
        
        # Add file directly to internal state (bypass normal add_file)
        async with state_manager._lock:
            state_manager._files_by_id[paused_file.id] = paused_file
        
        # Test that should_skip_file_processing returns True for paused file
        should_skip = await state_manager.should_skip_file_processing(paused_file.file_path)
        
        assert should_skip is True, (
            f"CRITICAL BUG: should_skip_file_processing returned False for "
            f"PAUSED_GROWING_COPY file! This will cause network interruption "
            f"recovery to fail as paused files will be rediscovered."
        )

    @pytest.mark.asyncio
    async def test_should_skip_all_paused_statuses(self):
        """Test that all paused statuses are properly skipped."""
        state_manager = StateManager(AsyncMock())
        
        paused_statuses = [
            FileStatus.PAUSED_IN_QUEUE,
            FileStatus.PAUSED_COPYING,
            FileStatus.PAUSED_GROWING_COPY,
        ]
        
        for status in paused_statuses:
            # Create file with paused status
            paused_file = TrackedFile(
                id=f"test-uuid-{status.value}",
                file_path=f"c:\\temp_input\\test_{status.value}.mxf",
                status=status,
                file_size=1000000,
                discovered_at=datetime.now()
            )
            
            # Add file to state manager first 
            added_file = await state_manager.add_file(
                file_path=paused_file.file_path,
                file_size=paused_file.file_size
            )
            
            # Then update to paused status
            await state_manager.update_file_status_by_id(
                file_id=added_file.id,
                status=status
            )
            
            # Test that file is skipped
            should_skip = await state_manager.should_skip_file_processing(paused_file.file_path)
            
            assert should_skip is True, (
                f"CRITICAL BUG: should_skip_file_processing returned False for "
                f"paused status {status.value}! Paused files must be skipped "
                f"to prevent rediscovery during network recovery."
            )

    @pytest.mark.asyncio
    async def test_should_not_skip_active_files(self):
        """Test that active (non-paused) files are NOT skipped."""
        state_manager = StateManager(AsyncMock())
        
        active_statuses = [
            FileStatus.DISCOVERED,
            FileStatus.READY_TO_START_GROWING,
            FileStatus.GROWING_COPY,
            FileStatus.IN_QUEUE,
            FileStatus.COPYING,
            FileStatus.WAITING_FOR_SPACE,
        ]
        
        for status in active_statuses:
            # Create file with active status
            active_file = TrackedFile(
                id=f"test-uuid-{status.value}",
                file_path=f"c:\\temp_input\\test_{status.value}.mxf",
                status=status,
                file_size=1000000,
                discovered_at=datetime.now()
            )
            
            # Add file to state manager first
            added_file = await state_manager.add_file(
                file_path=active_file.file_path,
                file_size=active_file.file_size
            )
            
            # Then update to active status
            await state_manager.update_file_status_by_id(
                file_id=added_file.id,
                status=status
            )
            
            # Test that file is NOT skipped
            should_skip = await state_manager.should_skip_file_processing(active_file.file_path)
            
            assert should_skip is False, (
                f"BUG: should_skip_file_processing returned True for "
                f"active status {status.value}! Active files should be processed normally."
            )

    @pytest.mark.asyncio
    async def test_should_not_skip_unknown_files(self):
        """Test that unknown (untracked) files are NOT skipped."""
        state_manager = StateManager(AsyncMock())
        
        # Test with file that doesn't exist in state manager
        unknown_file_path = "c:\\temp_input\\unknown_file.mxf"
        
        should_skip = await state_manager.should_skip_file_processing(unknown_file_path)
        
        assert should_skip is False, (
            f"BUG: should_skip_file_processing returned True for unknown file! "
            f"Unknown files should be processed normally for discovery."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])