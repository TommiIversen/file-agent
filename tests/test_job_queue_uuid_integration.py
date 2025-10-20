"""
Test suite for Job Queue UUID Integration.

Tests that verify job queue service works correctly with the new UUID-based
StateManager, focusing on job metadata and file tracking through the copy pipeline.
"""

import pytest
from unittest.mock import Mock

from app.models import FileStatus
from app.services.state_manager import StateManager
from app.services.job_queue import JobQueueService
from app.config import Settings
from app.dependencies import reset_singletons

# Mark all tests as async
pytestmark = pytest.mark.asyncio


class TestJobQueueUUIDIntegration:
    """Test suite for Job Queue services integration with UUID system."""

    @pytest.fixture
    def state_manager(self):
        """Fresh StateManager instance for each test."""
        reset_singletons()
        return StateManager()

    @pytest.fixture
    def mock_settings(self):
        """Mock Settings for testing."""
        settings = Mock(spec=Settings)
        settings.copy_queue_maxsize = 100
        settings.destination_path = "/test/destination"
        settings.file_stable_time_seconds = 2
        return settings

    @pytest.fixture
    def job_queue_service(self, mock_settings, state_manager):
        """JobQueueService instance for testing."""
        return JobQueueService(mock_settings, state_manager)

    async def test_job_queue_tracks_file_through_uuid_system(
        self, job_queue_service, state_manager, mock_settings
    ):
        """Test at job queue tracker filer korrekt gennem UUID systemet."""
        
        file_path = "/test/source/video_001.mxf"
        
        # 1. Initialize queue manually for testing
        if job_queue_service.job_queue is None:
            import asyncio
            job_queue_service.job_queue = asyncio.Queue()
        
        # 2. Subscribe job queue to state changes (simulate producer pattern)
        state_manager.subscribe(job_queue_service._handle_state_change)
        
        # 3. Add file to StateManager (simulate scanner)
        tracked_file = await state_manager.add_file(file_path, 2048)
        original_uuid = tracked_file.id
        
        # 4. Set to READY (this will trigger job queue via subscription)
        await state_manager.update_file_status_by_id(tracked_file.id, FileStatus.READY)
        
        # 5. Verify file status updated to IN_QUEUE
        current_file = await state_manager.get_file_by_id(tracked_file.id)
        assert current_file is not None
        assert current_file.status == FileStatus.IN_QUEUE
        assert current_file.id == original_uuid  # Same UUID maintained
        
        # 6. Verify queue contains the job
        assert job_queue_service.job_queue.qsize() == 1
        
        # 7. Get job from queue (simulate consumer)
        job = await job_queue_service.job_queue.get()
        assert job["file_path"] == file_path
        assert job["file_size"] == 2048
        assert "added_to_queue_at" in job

    async def test_job_queue_handles_file_that_returns_after_removal(
        self, job_queue_service, state_manager, mock_settings
    ):
        """Test job queue håndtering når fil kommer tilbage efter REMOVED status."""
        
        file_path = "/test/source/video_002.mxf"
        
        # 1. Initial file cycle
        tracked_file1 = await state_manager.add_file(file_path, 1024)
        await state_manager.update_file_status_by_id(tracked_file1.id, FileStatus.READY)
        
        # 2. File disappears (marked as REMOVED)
        await state_manager.cleanup_missing_files(set())
        removed_file = await state_manager.get_file_by_id(tracked_file1.id)
        assert removed_file is None  # REMOVED files excluded from get_file
        
        # 3. Same file returns (new UUID)
        tracked_file2 = await state_manager.add_file(file_path, 1500)  # Different size
        await state_manager.update_file_status_by_id(tracked_file2.id, FileStatus.READY)
        
        # 4. Initialize job queue and subscribe
        if job_queue_service.job_queue is None:
            import asyncio
            job_queue_service.job_queue = asyncio.Queue()
        state_manager.subscribe(job_queue_service._handle_state_change)
        
        # Trigger new state change to process into queue (redundant call removed)
        # File is already READY from previous call
        
        # 5. Verify correct file is in queue (new UUID, new size)
        current_file = await state_manager.get_file_by_id(tracked_file2.id)
        assert current_file.id == tracked_file2.id
        assert current_file.id != tracked_file1.id  # Different UUID
        assert current_file.file_size == 1500
        assert current_file.status == FileStatus.IN_QUEUE
        
        # 6. Verify history exists
        history = await state_manager.get_file_history(file_path)
        assert len(history) == 2  # Current + REMOVED
        
        current_entry = next(f for f in history if f.status != FileStatus.REMOVED)
        removed_entry = next(f for f in history if f.status == FileStatus.REMOVED)
        
        assert current_entry.id == tracked_file2.id
        assert removed_entry.id == tracked_file1.id

    async def test_job_queue_pause_resume_with_uuid_tracking(
        self, job_queue_service, state_manager, mock_settings
    ):
        """Test job queue pause/resume functionality med UUID tracking."""
        
        file_path = "/test/source/video_003.mxf"
        
        # 1. Add file and start copying
        tracked_file = await state_manager.add_file(file_path, 3072)
        original_uuid = tracked_file.id
        await state_manager.update_file_status_by_id(tracked_file.id, FileStatus.COPYING, copy_progress=25.0, bytes_copied=768)
        
        # 2. Pause operation (simulate destination unavailable)
        await job_queue_service.handle_destination_unavailable()
        
        # 3. Verify file is paused with preserved context
        paused_file = await state_manager.get_file_by_id(tracked_file.id)
        assert paused_file is not None
        assert paused_file.id == original_uuid  # Same UUID
        assert paused_file.status == FileStatus.PAUSED_COPYING
        assert paused_file.copy_progress == 25.0  # Preserved
        assert paused_file.bytes_copied == 768    # Preserved
        
        # 4. Resume operation 
        await job_queue_service.handle_destination_recovery()
        
        # 5. Verify file resumed with preserved context
        resumed_file = await state_manager.get_file_by_id(tracked_file.id)
        assert resumed_file is not None
        assert resumed_file.id == original_uuid  # Same UUID
        assert resumed_file.status == FileStatus.COPYING  # Resumed
        assert resumed_file.copy_progress == 25.0  # Preserved
        assert resumed_file.bytes_copied == 768    # Preserved
        assert resumed_file.retry_count == 0       # Reset

    async def test_job_queue_with_uuid_based_updates(
        self, job_queue_service, state_manager, mock_settings
    ):
        """Test at job queue kan bruge UUID-baserede updates for præcision."""
        
        file_path = "/test/source/video_004.mxf"
        
        # 1. Add file to StateManager
        tracked_file = await state_manager.add_file(file_path, 4096)
        original_uuid = tracked_file.id
        
        # 2. Use UUID-based update (new capability)
        result = await state_manager.update_file_status_by_id(
            original_uuid,
            FileStatus.READY,
            copy_progress=0.0
        )
        assert result is not None
        assert result.id == original_uuid
        
        # 3. Initialize job queue and subscribe  
        if job_queue_service.job_queue is None:
            import asyncio
            job_queue_service.job_queue = asyncio.Queue()
        state_manager.subscribe(job_queue_service._handle_state_change)
        
        # 4. Verify both path-based and UUID-based access work
        by_id = await state_manager.get_file_by_id(original_uuid)
        assert by_id.id == original_uuid
        assert by_id.status == FileStatus.IN_QUEUE

        # 5. Update via UUID (precise control)
        await state_manager.update_file_status_by_id(
            original_uuid,
            FileStatus.COPYING,
            copy_progress=50.0,
            copy_speed_mbps=12.5
        )
        
        # 6. Verify updates applied correctly
        updated_file = await state_manager.get_file_by_id(original_uuid)
        assert updated_file.status == FileStatus.COPYING
        assert updated_file.copy_progress == 50.0
        assert updated_file.copy_speed_mbps == 12.5

    async def test_job_queue_benefits_from_uuid_history_tracking(
        self, job_queue_service, state_manager, mock_settings
    ):
        """Test at job queue automatisk får benefit af UUID historie tracking."""
        
        file_path = "/test/source/recurring_render.mxf"
        
        # Simulate multiple job cycles for same filename
        job_uuids = []
        
        for cycle in range(3):
            # 1. File appears with different size each time
            tracked_file = await state_manager.add_file(file_path, 1000 * (cycle + 1))
            job_uuids.append(tracked_file.id)
            
            # 2. File goes through job queue (one-time initialization)
            if cycle == 0:
                if job_queue_service.job_queue is None:
                    import asyncio
                    job_queue_service.job_queue = asyncio.Queue()
                state_manager.subscribe(job_queue_service._handle_state_change)
            
            await state_manager.update_file_status_by_id(tracked_file.id, FileStatus.READY)
            
            # 3. File processed
            await state_manager.update_file_status_by_id(tracked_file.id, FileStatus.COPYING)
            
            # 4. File disappears (simulate completion + deletion)
            await state_manager.update_file_status_by_id(tracked_file.id, FileStatus.READY)  # Back to ready so it can be REMOVED
            await state_manager.cleanup_missing_files(set())
        
        # Verify we have complete history
        history = await state_manager.get_file_history(file_path)
        assert len(history) == 3
        
        # All entries should be REMOVED now
        for entry in history:
            assert entry.status == FileStatus.REMOVED
        
        # All should have unique UUIDs from job processing
        history_uuids = [entry.id for entry in history]
        assert len(set(history_uuids)) == 3
        assert set(history_uuids) == set(job_uuids)
        
        # File sizes should be preserved in history
        file_sizes = sorted([entry.file_size for entry in history])
        expected_sizes = [1000, 2000, 3000]
        assert file_sizes == expected_sizes

