"""Test network recovery re-evaluation of growing files"""

import pytest
from unittest.mock import AsyncMock, Mock

from app.models import FileStatus, TrackedFile
from app.services.job_queue import JobQueueService
from app.services.state_manager import StateManager
from app.services.storage_monitor.storage_monitor import StorageMonitorService
from app.config import Settings


@pytest.fixture
def mock_settings():
    """Mock settings for testing"""
    settings = Mock(spec=Settings)
    return settings


@pytest.fixture
def mock_state_manager():
    """Mock state manager for testing"""
    manager = AsyncMock(spec=StateManager)
    return manager


@pytest.fixture
def mock_storage_monitor():
    """Mock storage monitor for testing"""
    monitor = Mock(spec=StorageMonitorService)

    # Mock storage state
    storage_state = Mock()
    dest_info = Mock()
    dest_info.status = Mock()
    storage_state.get_destination_info.return_value = dest_info
    monitor._storage_state = storage_state

    return monitor


@pytest.fixture
def job_queue(mock_settings, mock_state_manager, mock_storage_monitor):
    """Create JobQueueService instance for testing"""
    queue = JobQueueService(
        settings=mock_settings,
        state_manager=mock_state_manager,
        storage_monitor=mock_storage_monitor,
    )
    return queue


@pytest.mark.asyncio
async def test_network_recovery_sets_files_to_discovered_for_reevaluation(
    job_queue, mock_state_manager
):
    """Test that network recovery sets waiting files back to DISCOVERED for re-evaluation"""

    # Create mock tracked files waiting for network
    tracked_files = [
        TrackedFile(
            id="file1-uuid",
            file_path="c:/temp/test1.mxf",
            file_name="test1.mxf",
            size=1000,
            status=FileStatus.WAITING_FOR_NETWORK,
        ),
        TrackedFile(
            id="file2-uuid",
            file_path="c:/temp/test2.mxv",
            file_name="test2.mxv",
            size=2000,
            status=FileStatus.WAITING_FOR_NETWORK,
        ),
    ]

    # Mock state manager to return waiting files
    mock_state_manager.get_files_by_status.return_value = tracked_files

    # Process waiting files
    await job_queue.process_waiting_network_files()

    # Verify get_files_by_status was called with correct status
    mock_state_manager.get_files_by_status.assert_called_once_with(
        FileStatus.WAITING_FOR_NETWORK
    )

    # Verify each file was set to DISCOVERED status for re-evaluation
    expected_calls = [
        mock_state_manager.update_file_status_by_id.call_args_list[0],
        mock_state_manager.update_file_status_by_id.call_args_list[1],
    ]

    # Check first file
    args, kwargs = expected_calls[0]
    assert kwargs["file_id"] == "file1-uuid"
    assert kwargs["status"] == FileStatus.DISCOVERED
    assert kwargs["error_message"] is None

    # Check second file
    args, kwargs = expected_calls[1]
    assert kwargs["file_id"] == "file2-uuid"
    assert kwargs["status"] == FileStatus.DISCOVERED
    assert kwargs["error_message"] is None

    # Verify update was called twice (once per file)
    assert mock_state_manager.update_file_status_by_id.call_count == 2


@pytest.mark.asyncio
async def test_network_recovery_with_no_waiting_files(job_queue, mock_state_manager):
    """Test network recovery when no files are waiting"""

    # Mock no waiting files
    mock_state_manager.get_files_by_status.return_value = []

    # Process waiting files
    await job_queue.process_waiting_network_files()

    # Verify get_files_by_status was called
    mock_state_manager.get_files_by_status.assert_called_once_with(
        FileStatus.WAITING_FOR_NETWORK
    )

    # Verify no status updates were made
    mock_state_manager.update_file_status_by_id.assert_not_called()


@pytest.mark.asyncio
async def test_network_recovery_handles_update_errors_gracefully(
    job_queue, mock_state_manager
):
    """Test that network recovery handles individual file update errors gracefully"""

    # Create mock tracked files
    tracked_files = [
        TrackedFile(
            id="file1-uuid",
            file_path="c:/temp/test1.mxf",
            file_name="test1.mxf",
            size=1000,
            status=FileStatus.WAITING_FOR_NETWORK,
        ),
        TrackedFile(
            id="file2-uuid",
            file_path="c:/temp/test2.mxv",
            file_name="test2.mxv",
            size=2000,
            status=FileStatus.WAITING_FOR_NETWORK,
        ),
    ]

    mock_state_manager.get_files_by_status.return_value = tracked_files

    # Make first update fail, second succeed
    mock_state_manager.update_file_status_by_id.side_effect = [
        Exception("Database error"),
        None,  # Success for second file
    ]

    # Process waiting files - should not raise exception
    await job_queue.process_waiting_network_files()

    # Verify both updates were attempted
    assert mock_state_manager.update_file_status_by_id.call_count == 2


@pytest.mark.asyncio
async def test_network_recovery_logs_reactivation_messages(
    job_queue, mock_state_manager, caplog
):
    """Test that network recovery logs appropriate reactivation messages"""

    import logging

    caplog.set_level(logging.INFO)

    tracked_files = [
        TrackedFile(
            id="file1-uuid",
            file_path="c:/temp/test.mxf",
            file_name="test.mxf",
            size=1000,
            status=FileStatus.WAITING_FOR_NETWORK,
        )
    ]

    mock_state_manager.get_files_by_status.return_value = tracked_files

    await job_queue.process_waiting_network_files()

    # Check for reactivation log message
    assert (
        "🔄 NETWORK RECOVERY: Reactivated c:/temp/test.mxf for re-evaluation"
        in caplog.text
    )
    assert "✅ NETWORK RECOVERY: Completed processing 1 files" in caplog.text
