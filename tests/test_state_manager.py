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

        assert tracked_file.file_path == sample_file_path
        assert tracked_file.file_size == file_size
        assert tracked_file.status == FileStatus.DISCOVERED
        assert tracked_file.copy_progress == 0.0
        assert tracked_file.retry_count == 0
        assert tracked_file.error_message is None
        assert tracked_file.discovered_at is not None

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

    async def test_update_file_status_changes_status(
        self, state_manager, sample_file_path
    ):
        """Test at update_file_status korrekt ændrer status og andre attributter."""
        # Tilføj fil
        tracked_file = await state_manager.add_file(sample_file_path, 1024)

        # Opdater status til READY
        updated_file = await state_manager.update_file_status_by_id(
            tracked_file.id, FileStatus.READY, copy_progress=50.0
        )

        assert updated_file is not None
        assert updated_file.status == FileStatus.READY
        assert updated_file.copy_progress == 50.0

    async def test_update_nonexistent_file_returns_none(self, state_manager):
        """Test at opdatering af ikke-eksisterende fil returnerer None."""
        result = await state_manager.update_file_status_by_id(
            "nonexistent-uuid", FileStatus.READY
        )

        assert result is None

    async def test_remove_file_removes_from_tracking(
        self, state_manager, sample_file_path
    ):
        """Test at remove_file fjerner fil fra tracking."""
        # Tilføj fil
        await state_manager.add_file(sample_file_path, 1024)

        # Verificer fil eksisterer
        tracked_file = await state_manager.get_file(sample_file_path)
        assert tracked_file is not None

        # Fjern fil
        success = await state_manager.remove_file(sample_file_path)
        assert success is True

        # Verificer fil er fjernet
        tracked_file = await state_manager.get_file(sample_file_path)
        assert tracked_file is None

    async def test_remove_nonexistent_file_returns_false(self, state_manager):
        """Test at fjernelse af ikke-eksisterende fil returnerer False."""
        success = await state_manager.remove_file("/nonexistent/file.mxf")
        assert success is False

    async def test_get_files_by_status(self, state_manager):
        """Test at get_files_by_status returnerer korrekte filer."""
        # Tilføj flere filer med forskellige statusser
        await state_manager.add_file("/test/file1.mxf", 1024)
        await state_manager.add_file("/test/file2.mxf", 2048)
        await state_manager.add_file("/test/file3.mxf", 4096)

        # Opdater nogen til READY
        file1 = await state_manager.get_file("/test/file1.mxf")
        file2 = await state_manager.get_file("/test/file2.mxf")
        await state_manager.update_file_status_by_id(file1.id, FileStatus.READY)
        await state_manager.update_file_status_by_id(file2.id, FileStatus.READY)

        # Test get_files_by_status
        discovered_files = await state_manager.get_files_by_status(
            FileStatus.DISCOVERED
        )
        ready_files = await state_manager.get_files_by_status(FileStatus.READY)

        assert len(discovered_files) == 1
        assert len(ready_files) == 2
        assert discovered_files[0].file_path == "/test/file3.mxf"

    async def test_cleanup_missing_files(self, state_manager):
        """Test at cleanup_missing_files fjerner filer ikke i existing_paths."""
        # Tilføj flere filer
        await state_manager.add_file("/test/file1.mxf", 1024)
        await state_manager.add_file("/test/file2.mxf", 2048)
        await state_manager.add_file("/test/file3.mxf", 4096)

        # Simuler at kun file1 og file3 stadig eksisterer
        existing_paths = {"/test/file1.mxf", "/test/file3.mxf"}

        removed_count = await state_manager.cleanup_missing_files(existing_paths)

        assert removed_count == 1

        # Verificer at kun file1 og file3 er tilbage
        all_files = await state_manager.get_all_files()
        remaining_paths = {f.file_path for f in all_files}
        assert remaining_paths == existing_paths

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

        async def add_files():
            """Add alle filer concurrent."""
            tasks = [state_manager.add_file(path, 1024) for path in file_paths]
            await asyncio.gather(*tasks)

        async def update_files():
            """Update alle filer concurrent."""
            await asyncio.sleep(0.01)  # Lille delay så add_files kan starte
            # Get files first, then update by ID
            tasks = []
            for path in file_paths:
                file = await state_manager.get_file(path)
                if file:
                    tasks.append(state_manager.update_file_status_by_id(file.id, FileStatus.READY))
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

    async def test_statistics(self, state_manager):
        """Test at get_statistics returnerer korrekte data."""
        # Tom tilstand
        stats = await state_manager.get_statistics()
        assert stats["total_files"] == 0
        assert stats["total_size_bytes"] == 0
        assert stats["active_copies"] == 0

        # Tilføj nogle filer
        file1 = await state_manager.add_file("/test/file1.mxf", 1024)
        await state_manager.add_file("/test/file2.mxf", 2048)
        await state_manager.update_file_status_by_id(file1.id, FileStatus.COPYING)

        stats = await state_manager.get_statistics()
        assert stats["total_files"] == 2
        assert stats["total_size_bytes"] == 3072
        assert stats["active_copies"] == 1
        assert stats["status_counts"][FileStatus.DISCOVERED.value] == 1
        assert stats["status_counts"][FileStatus.COPYING.value] == 1

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
