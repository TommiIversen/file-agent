"""Test network recovery re-evaluation of growing files"""

import pytest
from unittest.mock import AsyncMock, Mock

from app.models import FileStatus, TrackedFile
from app.services.job_queue import JobQueueService
from app.core.file_repository import FileRepository
from app.services.storage_monitor.storage_monitor import StorageMonitorService
from app.config import Settings
from app.core.events.event_bus import DomainEventBus


@pytest.fixture
def mock_settings():
    """Mock settings for testing"""
    settings = Mock(spec=Settings)
    return settings


@pytest.fixture
def mock_file_repository():
    """Mock file repository for testing"""
    repo = AsyncMock(spec=FileRepository)
    return repo


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
def mock_event_bus():
    return AsyncMock(spec=DomainEventBus)


@pytest.fixture
def job_queue(mock_settings, mock_file_repository, mock_storage_monitor, mock_event_bus):
    """Create JobQueueService instance for testing"""
    from unittest.mock import AsyncMock
    from app.core.file_state_machine import FileStateMachine
    mock_state_machine = AsyncMock(spec=FileStateMachine)
    
    queue = JobQueueService(
        settings=mock_settings,
        file_repository=mock_file_repository,
        storage_monitor=mock_storage_monitor,
        event_bus=mock_event_bus,
        state_machine=mock_state_machine
    )
    # Store reference to mock_state_machine for test access
    queue._test_state_machine = mock_state_machine
    return queue


@pytest.mark.asyncio
async def test_network_recovery_sets_files_to_discovered_for_reevaluation(
    job_queue, mock_file_repository, mock_event_bus
):
    """Test that network recovery sets waiting files back to DISCOVERED for re-evaluation"""

    # Create mock tracked files waiting for network
    tracked_files = [
        TrackedFile(
            id="file1-uuid",
            file_path="c:/temp/test1.mxf",
            file_name="test1.mxf",
            file_size=1000,
            status=FileStatus.WAITING_FOR_NETWORK,
        ),
        TrackedFile(
            id="file2-uuid",
            file_path="c:/temp/test2.mxv",
            file_name="test2.mxv",
            file_size=2000,
            status=FileStatus.WAITING_FOR_NETWORK,
        ),
    ]

    # Mock repository to return waiting files
    mock_file_repository.get_all.return_value = tracked_files

    # Process waiting files
    await job_queue.process_waiting_network_files()

    # Verify get_all was called
    mock_file_repository.get_all.assert_called_once()

    # Verify each file was transitioned to DISCOVERED status via state machine
    assert job_queue._test_state_machine.transition.call_count == 2
    
    # Check the first file state transition
    call1 = job_queue._test_state_machine.transition.call_args_list[0]
    assert call1.kwargs['file_id'] == "file1-uuid"
    assert call1.kwargs['new_status'] == FileStatus.DISCOVERED
    assert call1.kwargs['error_message'] is None

    # Check the second file state transition
    call2 = job_queue._test_state_machine.transition.call_args_list[1]
    assert call2.kwargs['file_id'] == "file2-uuid"
    assert call2.kwargs['new_status'] == FileStatus.DISCOVERED

    # Note: Events are published by the state machine, not directly by the job queue



@pytest.mark.asyncio
async def test_network_recovery_with_no_waiting_files(job_queue, mock_file_repository):
    """Test network recovery when no files are waiting"""

    # Mock no waiting files
    mock_file_repository.get_all.return_value = []

    # Process waiting files
    await job_queue.process_waiting_network_files()

    # Verify get_all was called
    mock_file_repository.get_all.assert_called_once()

    # Verify no status updates were made
    mock_file_repository.update.assert_not_called()


@pytest.mark.asyncio
async def test_network_recovery_handles_update_errors_gracefully(
    job_queue, mock_file_repository
):
    """Test that network recovery handles individual file update errors gracefully"""

    # Create mock tracked files
    tracked_files = [
        TrackedFile(
            id="file1-uuid",
            file_path="c:/temp/test1.mxf",
            file_name="test1.mxf",
            file_size=1000,
            status=FileStatus.WAITING_FOR_NETWORK,
        ),
        TrackedFile(
            id="file2-uuid",
            file_path="c:/temp/test2.mxv",
            file_name="test2.mxv",
            file_size=2000,
            status=FileStatus.WAITING_FOR_NETWORK,
        ),
    ]

    mock_file_repository.get_all.return_value = tracked_files

    # Make first state machine transition fail, second succeed
    job_queue._test_state_machine.transition.side_effect = [
        Exception("State machine error"),
        None,  # Success for second file
    ]

    # Process waiting files - should not raise exception
    await job_queue.process_waiting_network_files()

    # Verify both state machine transitions were attempted
    assert job_queue._test_state_machine.transition.call_count == 2


@pytest.mark.asyncio
async def test_network_recovery_logs_reactivation_messages(
    job_queue, mock_file_repository, caplog
):
    """Test that network recovery logs appropriate reactivation messages"""

    import logging

    caplog.set_level(logging.INFO)

    tracked_files = [
        TrackedFile(
            id="file1-uuid",
            file_path="c:/temp/test.mxf",
            file_name="test.mxf",
            file_size=1000,
            status=FileStatus.WAITING_FOR_NETWORK,
        )
    ]

    mock_file_repository.get_all.return_value = tracked_files

    await job_queue.process_waiting_network_files()

    # Check for reactivation log message
    assert (
        "🔄 NETWORK RECOVERY: Reactivated c:/temp/test.mxf for re-evaluation"
        in caplog.text
    )
    assert "✅ NETWORK RECOVERY: Completed processing 1 files" in caplog.text
