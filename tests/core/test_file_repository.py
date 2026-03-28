"""
Tests for FileRepository — the in-memory data access layer for TrackedFile objects.
Covers CRUD operations, duplicate handling, the update bug fix, and prune logic.
"""
import pytest
from datetime import datetime, timedelta

from app.core.file_repository import FileRepository
from app.models import TrackedFile, FileStatus


def _make_file(
    file_id: str = "test-1",
    status: FileStatus = FileStatus.DISCOVERED,
    discovered_at: datetime = None,
    completed_at: datetime = None,
    failed_at: datetime = None,
    space_error_at: datetime = None,
) -> TrackedFile:
    return TrackedFile(
        id=file_id,
        file_path=f"/test/{file_id}.mxf",
        file_size=1000,
        status=status,
        discovered_at=discovered_at or datetime.now(),
        completed_at=completed_at,
        failed_at=failed_at,
        space_error_at=space_error_at,
    )


class TestFileRepositoryCRUD:

    @pytest.mark.asyncio
    async def test_add_and_get_by_id(self):
        repo = FileRepository()
        f = _make_file("f1")
        await repo.add(f)
        result = await repo.get_by_id("f1")
        assert result is not None
        assert result.id == "f1"

    @pytest.mark.asyncio
    async def test_get_by_id_returns_none_for_missing(self):
        repo = FileRepository()
        assert await repo.get_by_id("nonexistent") is None

    @pytest.mark.asyncio
    async def test_add_duplicate_is_ignored(self):
        repo = FileRepository()
        f1 = _make_file("dup", status=FileStatus.DISCOVERED)
        f2 = _make_file("dup", status=FileStatus.READY)
        await repo.add(f1)
        await repo.add(f2)  # should be silently ignored
        result = await repo.get_by_id("dup")
        assert result.status == FileStatus.DISCOVERED  # original kept

    @pytest.mark.asyncio
    async def test_get_all(self):
        repo = FileRepository()
        await repo.add(_make_file("a"))
        await repo.add(_make_file("b"))
        all_files = await repo.get_all()
        ids = {f.id for f in all_files}
        assert ids == {"a", "b"}

    @pytest.mark.asyncio
    async def test_get_all_returns_copy(self):
        repo = FileRepository()
        await repo.add(_make_file("x"))
        list1 = await repo.get_all()
        list2 = await repo.get_all()
        assert list1 is not list2  # different list objects

    @pytest.mark.asyncio
    async def test_update_existing_file(self):
        repo = FileRepository()
        f = _make_file("u1")
        await repo.add(f)
        updated = f.model_copy(update={"status": FileStatus.READY})
        await repo.update(updated)
        result = await repo.get_by_id("u1")
        assert result.status == FileStatus.READY

    @pytest.mark.asyncio
    async def test_update_nonexistent_file_is_noop(self):
        """Bug fix: update() must NOT silently insert unknown files."""
        repo = FileRepository()
        phantom = _make_file("phantom")
        await repo.update(phantom)
        assert await repo.get_by_id("phantom") is None
        assert await repo.count() == 0

    @pytest.mark.asyncio
    async def test_remove_existing(self):
        repo = FileRepository()
        await repo.add(_make_file("r1"))
        removed = await repo.remove("r1")
        assert removed is True
        assert await repo.get_by_id("r1") is None

    @pytest.mark.asyncio
    async def test_remove_nonexistent_returns_false(self):
        repo = FileRepository()
        assert await repo.remove("nope") is False

    @pytest.mark.asyncio
    async def test_count(self):
        repo = FileRepository()
        assert await repo.count() == 0
        await repo.add(_make_file("c1"))
        await repo.add(_make_file("c2"))
        assert await repo.count() == 2


class TestFileRepositoryPrune:

    @pytest.mark.asyncio
    async def test_prune_removes_old_completed_files(self):
        repo = FileRepository()
        old_time = datetime.now() - timedelta(days=30)
        await repo.add(_make_file("old", status=FileStatus.COMPLETED, completed_at=old_time, discovered_at=old_time))
        await repo.add(_make_file("new", status=FileStatus.COMPLETED, completed_at=datetime.now()))

        cutoff = datetime.now() - timedelta(days=7)
        pruned = await repo.prune_terminal_files({FileStatus.COMPLETED, FileStatus.FAILED}, cutoff)

        assert pruned == 1
        assert await repo.get_by_id("old") is None
        assert await repo.get_by_id("new") is not None

    @pytest.mark.asyncio
    async def test_prune_removes_old_failed_files(self):
        repo = FileRepository()
        old_time = datetime.now() - timedelta(days=30)
        await repo.add(_make_file("old-fail", status=FileStatus.FAILED, failed_at=old_time, discovered_at=old_time))

        cutoff = datetime.now() - timedelta(days=7)
        pruned = await repo.prune_terminal_files({FileStatus.COMPLETED, FileStatus.FAILED}, cutoff)
        assert pruned == 1

    @pytest.mark.asyncio
    async def test_prune_ignores_active_files(self):
        repo = FileRepository()
        old_time = datetime.now() - timedelta(days=30)
        await repo.add(_make_file("copying", status=FileStatus.COPYING, discovered_at=old_time))

        cutoff = datetime.now() - timedelta(days=7)
        pruned = await repo.prune_terminal_files({FileStatus.COMPLETED, FileStatus.FAILED}, cutoff)
        assert pruned == 0
        assert await repo.get_by_id("copying") is not None

    @pytest.mark.asyncio
    async def test_prune_uses_timestamp_fallback_chain(self):
        """Tests the fallback: completed_at -> failed_at -> space_error_at -> discovered_at."""
        repo = FileRepository()
        old_time = datetime.now() - timedelta(days=30)

        # File with only space_error_at set
        await repo.add(_make_file(
            "space-err",
            status=FileStatus.SPACE_ERROR,
            space_error_at=old_time,
            discovered_at=old_time,
        ))

        cutoff = datetime.now() - timedelta(days=7)
        pruned = await repo.prune_terminal_files({FileStatus.SPACE_ERROR}, cutoff)
        assert pruned == 1

    @pytest.mark.asyncio
    async def test_prune_uses_discovered_at_as_final_fallback(self):
        repo = FileRepository()
        old_time = datetime.now() - timedelta(days=30)

        # File with only discovered_at (no completion timestamps)
        await repo.add(_make_file("only-disc", status=FileStatus.FAILED, discovered_at=old_time))

        cutoff = datetime.now() - timedelta(days=7)
        pruned = await repo.prune_terminal_files({FileStatus.FAILED}, cutoff)
        assert pruned == 1

    @pytest.mark.asyncio
    async def test_prune_returns_zero_on_empty_repo(self):
        repo = FileRepository()
        cutoff = datetime.now() - timedelta(days=7)
        pruned = await repo.prune_terminal_files({FileStatus.COMPLETED}, cutoff)
        assert pruned == 0

    @pytest.mark.asyncio
    async def test_prune_respects_cutoff_boundary(self):
        """File exactly at cutoff should NOT be pruned (must be strictly older)."""
        repo = FileRepository()
        cutoff = datetime.now() - timedelta(days=7)
        # completed_at exactly at cutoff
        await repo.add(_make_file("boundary", status=FileStatus.COMPLETED, completed_at=cutoff))
        pruned = await repo.prune_terminal_files({FileStatus.COMPLETED}, cutoff)
        assert pruned == 0  # exactly at cutoff, not strictly less than
