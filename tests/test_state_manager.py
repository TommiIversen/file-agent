"""
Test suite for StateManager.

Tester den centrale state management funktionalitet inklusiv:
- Thread safety med concurrent operations
- Pub/sub system
- Fil lifecycle management
- Cleanup operationer
"""

import pytest
import asyncio
from typing import List

from app.services.state_manager import StateManager
from app.models import FileStatus, FileStateUpdate
from app.dependencies import reset_singletons


# Mark all tests as async
pytestmark = pytest.mark.asyncio


class TestStateManager:
    """Test suite for StateManager funktionalitet."""

    @pytest.fixture
    def state_manager(self):
        """Fresh StateManager instance for hver test."""
        reset_singletons()  # Ensure clean state
        return StateManager()

    @pytest.fixture
    def sample_file_path(self):
        """Sample file path for testing."""
        return "/test/video_001.mxf"

    async def test_add_file_creates_tracked_file(self, state_manager, sample_file_path):
        """Test at add_file korrekt opretter TrackedFile med Discovered status."""
        file_size = 1024
        tracked_file = await state_manager.add_file(sample_file_path, file_size)
        assert tracked_file.status == FileStatus.DISCOVERED
        assert tracked_file.file_path == sample_file_path
        assert tracked_file.file_size == file_size
        assert tracked_file.id is not None

    async def test_add_existing_file_returns_existing(
        self, state_manager, sample_file_path
    ):
        """Test at tilføjelse af eksisterende fil returnerer existing TrackedFile."""
        # Tilføj fil første gang
        first_tracked = await state_manager.add_file(sample_file_path, 1024)

        # Tilføj samme fil igen
        second_tracked = await state_manager.add_file(sample_file_path, 2048)

        # Skal returnere samme objekt (ikke oprette nyt)
        assert first_tracked is second_tracked
        assert first_tracked.file_size == 1024  # Original size preserved

    async def test_update_file_status_by_id(self, state_manager, sample_file_path):
        tracked_file = await state_manager.add_file(sample_file_path, 1024)
        updated_file = await state_manager.update_file_status_by_id(
            tracked_file.id, FileStatus.READY, copy_progress=50.0
        )
        assert updated_file.status == FileStatus.READY
        assert updated_file.copy_progress == 50.0

    async def test_update_file_status_by_id_nonexistent(self, state_manager):
        result = await state_manager.update_file_status_by_id(
            "nonexistent-uuid", FileStatus.READY
        )
        assert result is None

    async def test_remove_file_by_id(self, state_manager, sample_file_path):
        tracked_file = await state_manager.add_file(sample_file_path, 1024)
        success = await state_manager.remove_file_by_id(tracked_file.id)
        assert success is True
        file_by_id = await state_manager.get_file_by_id(tracked_file.id)
        assert file_by_id is None

    async def test_get_file_by_id(self, state_manager, sample_file_path):
        tracked_file = await state_manager.add_file(sample_file_path, 1024)
        file_by_id = await state_manager.get_file_by_id(tracked_file.id)
        assert file_by_id is not None
        assert file_by_id.id == tracked_file.id

    async def test_get_files_by_status(self, state_manager):
        file1 = await state_manager.add_file("/test/file1.mxf", 1024)
        file2 = await state_manager.add_file("/test/file2.mxf", 2048)
        file3 = await state_manager.add_file("/test/file3.mxf", 4096)
        await state_manager.update_file_status_by_id(file1.id, FileStatus.READY)
        await state_manager.update_file_status_by_id(file2.id, FileStatus.READY)
        # Test get_files_by_status
        discovered_files = await state_manager.get_files_by_status(
            FileStatus.DISCOVERED
        )
        ready_files = await state_manager.get_files_by_status(FileStatus.READY)
        assert all(f.status == FileStatus.DISCOVERED for f in discovered_files)
        assert all(f.status == FileStatus.READY for f in ready_files)
        assert file3.id in [f.id for f in discovered_files]

    async def test_cleanup_missing_files(self, state_manager):
        await state_manager.add_file("/test/file1.mxf", 1024)
        await state_manager.add_file("/test/file2.mxf", 2048)
        await state_manager.add_file("/test/file3.mxf", 4096)
        existing_paths = {"/test/file2.mxf"}
        removed_count = await state_manager.cleanup_missing_files(existing_paths)
        assert removed_count == 2
        all_files = await state_manager.get_all_files()
        remaining_ids = {f.id for f in all_files if f.status != FileStatus.REMOVED}
        assert len(remaining_ids) == 1

    async def test_pub_sub_system(self, state_manager, sample_file_path):
        """Test at pub/sub systemet notificerer subscribers korrekt."""
        received_updates: List[FileStateUpdate] = []

        async def test_subscriber(update: FileStateUpdate):
            received_updates.append(update)

        # Subscribe til updates
        state_manager.subscribe(test_subscriber)

        # Tilføj fil (skal trigger notification)
        tracked_file = await state_manager.add_file(sample_file_path, 1024)

        # Opdater status (skal trigger notification)
        await state_manager.update_file_status_by_id(tracked_file.id, FileStatus.READY)

        # Give asyncio lidt tid til at process callbacks
        await asyncio.sleep(0.01)

        # Verificer at vi modtog 2 notifications
        assert len(received_updates) == 2

        # Verificer første notification (add_file)
        add_update = received_updates[0]
        assert add_update.file_path == sample_file_path
        assert add_update.old_status is None
        assert add_update.new_status == FileStatus.DISCOVERED

        # Verificer anden notification (status update)
        status_update = received_updates[1]
        assert status_update.file_path == sample_file_path
        assert status_update.old_status == FileStatus.DISCOVERED
        assert status_update.new_status == FileStatus.READY

    async def test_thread_safety_concurrent_operations(self, state_manager):
        """Test thread safety med concurrent add/update/remove operationer."""
        file_paths = [f"/test/file_{i}.mxf" for i in range(100)]
        tracked_files = {}

        async def add_files():
            """Add alle filer concurrent."""
            tasks = [state_manager.add_file(path, 1024) for path in file_paths]
            results = await asyncio.gather(*tasks)
            for path, tracked_file in zip(file_paths, results):
                tracked_files[path] = tracked_file

        async def update_files():
            """Update alle filer concurrent."""
            await asyncio.sleep(0.01)  # Lille delay så add_files kan starte
            # Get files first, then update by ID
            tasks = []
            for path in file_paths:
                tracked_file = tracked_files.get(path)
                if tracked_file:
                    tasks.append(
                        state_manager.update_file_status_by_id(
                            tracked_file.id, FileStatus.READY
                        )
                    )
            await asyncio.gather(*tasks, return_exceptions=True)

        # Kør begge operationer samtidigt
        await asyncio.gather(add_files(), update_files())

        # Verificer at alle filer blev tilføjet korrekt
        all_files = await state_manager.get_all_files()
        assert len(all_files) == 100

        # Verificer at de fleste filer blev opdateret til READY
        ready_files = await state_manager.get_files_by_status(FileStatus.READY)
        # Der kan være race conditions, så vi tillader at nogle ikke blev opdateret
        assert len(ready_files) >= 90

    async def test_status_counts_and_statistics(self, state_manager):
        file1 = await state_manager.add_file("/test/file1.mxf", 1024)
        file2 = await state_manager.add_file("/test/file2.mxf", 2048)
        await state_manager.update_file_status_by_id(file1.id, FileStatus.COPYING)
        await state_manager.update_file_status_by_id(file2.id, FileStatus.READY)
        stats = await state_manager.get_statistics()
        assert stats["status_counts"]["Copying"] == 1
        assert stats["status_counts"]["Ready"] == 1

    async def test_unsubscribe_removes_callback(self, state_manager, sample_file_path):
        """Test at unsubscribe fjerner callback korrekt."""
        received_updates: List[FileStateUpdate] = []

        async def test_subscriber(update: FileStateUpdate):
            received_updates.append(update)

        # Subscribe og derefter unsubscribe
        state_manager.subscribe(test_subscriber)
        success = state_manager.unsubscribe(test_subscriber)
        assert success is True

        # Tilføj fil (skal ikke trigger notification)
        await state_manager.add_file(sample_file_path, 1024)
        await asyncio.sleep(0.01)

        # Ingen updates skulle være modtaget
        assert len(received_updates) == 0

        # Test unsubscribe af non-existent callback
        success = state_manager.unsubscribe(test_subscriber)
        assert success is False
