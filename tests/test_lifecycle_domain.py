"""
Test for Lifecycle Domain
Verify that the lifecycle cleanup functionality works correctly.
"""
import asyncio
import pytest
from datetime import datetime, timedelta

from app.domains.lifecycle.commands import PruneOldFilesCommand
from app.domains.lifecycle.handlers import PruneOldFilesCommandHandler
from app.models import TrackedFile, FileStatus
from app.core.file_repository import InMemoryFileRepository as FileRepository


@pytest.mark.asyncio
async def test_prune_old_files_command_handler():
    """Test that the PruneOldFilesCommandHandler correctly uses the new repository method."""
    
    # Setup
    repository = FileRepository()
    handler = PruneOldFilesCommandHandler(repository)
    
    # Create test files - some old, some new, some in different states
    old_completed_file = TrackedFile(
        id="old-completed",
        file_path="/test/old_completed.mxv",
        file_size=1000,
        status=FileStatus.COMPLETED,
        discovered_at=datetime.now() - timedelta(days=20),  # 20 days old
        completed_at=datetime.now() - timedelta(days=20)
    )
    
    recent_completed_file = TrackedFile(
        id="recent-completed",
        file_path="/test/recent_completed.mxv",
        file_size=1000,
        status=FileStatus.COMPLETED,
        discovered_at=datetime.now() - timedelta(hours=1),  # 1 hour old
        completed_at=datetime.now() - timedelta(hours=1)
    )
    
    old_failed_file = TrackedFile(
        id="old-failed",
        file_path="/test/old_failed.mxv",
        file_size=1000,
        status=FileStatus.FAILED,
        discovered_at=datetime.now() - timedelta(days=20),
        failed_at=datetime.now() - timedelta(days=20)
    )
    
    active_file = TrackedFile(
        id="active-file",
        file_path="/test/active.mxv",
        file_size=1000,
        status=FileStatus.COPYING,  # Active, should not be removed
        discovered_at=datetime.now() - timedelta(days=20)
    )
    
    # Add files to repository
    await repository.add(old_completed_file)
    await repository.add(recent_completed_file)
    await repository.add(old_failed_file)
    await repository.add(active_file)
    
    # Verify initial state
    initial_count = await repository.count()
    assert initial_count == 4
    
    # Execute command to keep files for 7 days (168 hours)
    command = PruneOldFilesCommand(hours_to_keep=168)
    await handler.handle(command)
    
    # Verify results
    remaining_files = await repository.get_all()
    remaining_ids = [f.id for f in remaining_files]
    
    # Should have removed old terminal files, kept recent and active files
    assert "recent-completed" in remaining_ids  # Recent completed file should remain
    assert "active-file" in remaining_ids       # Active file should remain
    assert "old-completed" not in remaining_ids # Old completed file should be removed
    assert "old-failed" not in remaining_ids    # Old failed file should be removed
    
    final_count = await repository.count()
    assert final_count == 2  # Should have 2 files remaining


@pytest.mark.asyncio
async def test_repository_prune_terminal_files_directly():
    """Test the new prune_terminal_files method directly."""
    
    repository = FileRepository()
    
    # Setup terminal states
    terminal_states = {
        FileStatus.COMPLETED,
        FileStatus.COMPLETED_DELETE_FAILED,
        FileStatus.FAILED,
        FileStatus.REMOVED,
        FileStatus.SPACE_ERROR,
    }
    
    # Create test files
    old_completed_file = TrackedFile(
        id="old-completed",
        file_path="/test/old_completed.mxv",
        file_size=1000,
        status=FileStatus.COMPLETED,
        discovered_at=datetime.now() - timedelta(days=20),
        completed_at=datetime.now() - timedelta(days=20)
    )
    
    recent_completed_file = TrackedFile(
        id="recent-completed",
        file_path="/test/recent_completed.mxv",
        file_size=1000,
        status=FileStatus.COMPLETED,
        discovered_at=datetime.now() - timedelta(hours=1),
        completed_at=datetime.now() - timedelta(hours=1)
    )
    
    active_file = TrackedFile(
        id="active-file",
        file_path="/test/active.mxv",
        file_size=1000,
        status=FileStatus.COPYING,
        discovered_at=datetime.now() - timedelta(days=20)
    )
    
    # Add files to repository
    await repository.add(old_completed_file)
    await repository.add(recent_completed_file)
    await repository.add(active_file)
    
    # Execute prune directly on repository
    cutoff_date = datetime.now() - timedelta(days=7)  # 7 days ago
    pruned_count = await repository.prune_terminal_files(terminal_states, cutoff_date)
    
    # Verify results
    assert pruned_count == 1  # Only old completed file should be pruned
    
    remaining_files = await repository.get_all()
    remaining_ids = [f.id for f in remaining_files]
    
    assert "recent-completed" in remaining_ids  # Recent file should remain
    assert "active-file" in remaining_ids       # Active file should remain
    assert "old-completed" not in remaining_ids # Old file should be removed


@pytest.mark.asyncio
async def test_prune_no_old_files():
    """Test that the handler works correctly when there are no old files to remove."""
    
    repository = FileRepository()
    handler = PruneOldFilesCommandHandler(repository)
    
    # Create only recent files
    recent_file = TrackedFile(
        id="recent-file",
        file_path="/test/recent.mxv",
        file_size=1000,
        status=FileStatus.COMPLETED,
        discovered_at=datetime.now() - timedelta(hours=1),
        completed_at=datetime.now() - timedelta(hours=1)
    )
    
    await repository.add(recent_file)
    
    # Execute command
    command = PruneOldFilesCommand(hours_to_keep=168)  # 7 days
    await handler.handle(command)
    
    # Verify no files were removed
    final_count = await repository.count()
    assert final_count == 1
    
    remaining_file = await repository.get_by_id("recent-file")
    assert remaining_file is not None


if __name__ == "__main__":
    # Simple test runner for development
    asyncio.run(test_prune_old_files_command_handler())
    asyncio.run(test_repository_prune_terminal_files_directly())
    asyncio.run(test_prune_no_old_files())
    print("All lifecycle tests passed!")