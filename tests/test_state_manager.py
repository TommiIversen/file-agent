import pytest
import asyncio

from app.services.state_manager import StateManager
from app.models import FileStatus
from app.dependencies import reset_singletons


# Mark all tests as async
pytestmark = pytest.mark.asyncio


class TestStateManager:
    """Test suite for StateManager funktionalitet."""

    @pytest.fixture
    def state_manager(self):
        """Fresh StateManager instance for hver test."""
        reset_singletons()  # Ensure clean state
        from app.core.file_repository import FileRepository
        file_repository = FileRepository()
        return StateManager(file_repository=file_repository)

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

    async def test_schedule_retry_success(self, state_manager, sample_file_path):
        """Test successful retry scheduling."""
        # Add file
        tracked_file = await state_manager.add_file(sample_file_path, 1024)

        # Schedule retry
        result = await state_manager.schedule_retry(
            tracked_file.id, 0.1, "Test retry", "test"
        )
        assert result is True

        # Verify retry info is stored in TrackedFile
        updated_file = await state_manager.get_file_by_id(tracked_file.id)
        assert updated_file.retry_info is not None
        assert updated_file.retry_info.reason == "Test retry"
        assert updated_file.retry_info.retry_type == "test"

    async def test_schedule_retry_unknown_file(self, state_manager):
        """Test retry scheduling for unknown file."""
        result = await state_manager.schedule_retry(
            "unknown-id", 0.1, "Test retry", "test"
        )
        assert result is False

    async def test_cancel_retry_success(self, state_manager, sample_file_path):
        """Test successful retry cancellation."""
        # Add file and schedule retry
        tracked_file = await state_manager.add_file(sample_file_path, 1024)
        await state_manager.schedule_retry(tracked_file.id, 0.1, "Test retry", "test")

        # Cancel retry
        result = await state_manager.cancel_retry(tracked_file.id)
        assert result is True

    async def test_increment_retry_count(self, state_manager, sample_file_path):
        """Test retry count increment."""
        # Add file
        tracked_file = await state_manager.add_file(sample_file_path, 1024)
        assert tracked_file.retry_count == 0

        # Increment retry count
        new_count = await state_manager.increment_retry_count(tracked_file.id)
        assert new_count == 1

        # Verify file was updated
        updated_file = await state_manager.get_file_by_id(tracked_file.id)
        assert updated_file.retry_count == 1

    async def test_increment_retry_count_unknown_file(self, state_manager):
        """Test increment retry count for unknown file."""
        count = await state_manager.increment_retry_count("unknown-id")
        assert count == 0

    async def test_cancel_all_retries(self, state_manager):
        """Test cancelling all retries."""
        # Add multiple files and schedule retries
        file1 = await state_manager.add_file("/test/file1.mxf", 1024)
        file2 = await state_manager.add_file("/test/file2.mxf", 2048)

        await state_manager.schedule_retry(file1.id, 0.1, "Test retry 1", "test")
        await state_manager.schedule_retry(file2.id, 0.1, "Test retry 2", "test")

        # Cancel all retries
        cancelled_count = await state_manager.cancel_all_retries()
        assert cancelled_count == 2
