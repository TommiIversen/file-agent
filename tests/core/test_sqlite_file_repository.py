"""
Tests for SqliteFileRepository — persistent SQLite data access layer for TrackedFile objects.

Mirrors every test in test_file_repository.py to guarantee behavioural parity,
plus adds SQLite-specific tests for persistence, serialisation, and migrations.
"""

import asyncio
import pytest
import os
import tempfile
from datetime import datetime, timedelta

from app.core.sqlite_file_repository import SqliteFileRepository
from app.models import TrackedFile, FileStatus, RetryInfo


def _make_file(
    file_id: str = "test-1",
    status: FileStatus = FileStatus.DISCOVERED,
    discovered_at: datetime = None,
    completed_at: datetime = None,
    failed_at: datetime = None,
    space_error_at: datetime = None,
    retry_info: RetryInfo = None,
    file_size: int = 1000,
    destination_path: str = None,
    copy_progress: float = 0.0,
    bytes_copied: int = 0,
    copy_speed_mbps: float = 0.0,
    growth_rate_mbps: float = 0.0,
    previous_file_size: int = 0,
    first_seen_size: int = 0,
    growth_stable_since: datetime = None,
) -> TrackedFile:
    return TrackedFile(
        id=file_id,
        file_path=f"/test/{file_id}.mxf",
        file_size=file_size,
        status=status,
        discovered_at=discovered_at or datetime.now(),
        completed_at=completed_at,
        failed_at=failed_at,
        space_error_at=space_error_at,
        retry_info=retry_info,
        destination_path=destination_path,
        copy_progress=copy_progress,
        bytes_copied=bytes_copied,
        copy_speed_mbps=copy_speed_mbps,
        growth_rate_mbps=growth_rate_mbps,
        previous_file_size=previous_file_size,
        first_seen_size=first_seen_size,
        growth_stable_since=growth_stable_since,
    )


@pytest.fixture
async def repo(tmp_path):
    """Create a fresh SqliteFileRepository per test — fast, no Alembic."""
    db_path = str(tmp_path / "test.db")
    r = SqliteFileRepository(db_path)
    await r.init_db(run_migrations=False)
    await r.create_schema()
    yield r
    await r.close()


# ── CRUD Tests (parity with test_file_repository.py) ──────────────────────

class TestSqliteFileRepositoryCRUD:

    @pytest.mark.asyncio
    async def test_add_and_get_by_id(self, repo):
        f = _make_file("f1")
        await repo.add(f)
        result = await repo.get_by_id("f1")
        assert result is not None
        assert result.id == "f1"
        assert result.file_path == "/test/f1.mxf"

    @pytest.mark.asyncio
    async def test_get_by_id_returns_none_for_missing(self, repo):
        assert await repo.get_by_id("nonexistent") is None

    @pytest.mark.asyncio
    async def test_add_duplicate_is_ignored(self, repo):
        f1 = _make_file("dup", status=FileStatus.DISCOVERED)
        f2 = _make_file("dup", status=FileStatus.READY)
        await repo.add(f1)
        await repo.add(f2)  # should be silently ignored
        result = await repo.get_by_id("dup")
        assert result.status == FileStatus.DISCOVERED  # original kept

    @pytest.mark.asyncio
    async def test_get_all(self, repo):
        await repo.add(_make_file("a"))
        await repo.add(_make_file("b"))
        all_files = await repo.get_all()
        ids = {f.id for f in all_files}
        assert ids == {"a", "b"}

    @pytest.mark.asyncio
    async def test_get_all_returns_independent_list(self, repo):
        await repo.add(_make_file("x"))
        list1 = await repo.get_all()
        list2 = await repo.get_all()
        assert list1 is not list2

    @pytest.mark.asyncio
    async def test_update_existing_file(self, repo):
        f = _make_file("u1")
        await repo.add(f)
        updated = f.model_copy(update={"status": FileStatus.READY})
        await repo.update(updated)
        result = await repo.get_by_id("u1")
        assert result.status == FileStatus.READY

    @pytest.mark.asyncio
    async def test_update_nonexistent_file_is_noop(self, repo):
        """update() must NOT silently insert unknown files."""
        phantom = _make_file("phantom")
        await repo.update(phantom)
        assert await repo.get_by_id("phantom") is None
        assert await repo.count() == 0

    @pytest.mark.asyncio
    async def test_remove_existing(self, repo):
        await repo.add(_make_file("r1"))
        removed = await repo.remove("r1")
        assert removed is True
        assert await repo.get_by_id("r1") is None

    @pytest.mark.asyncio
    async def test_remove_nonexistent_returns_false(self, repo):
        assert await repo.remove("nope") is False

    @pytest.mark.asyncio
    async def test_count(self, repo):
        assert await repo.count() == 0
        await repo.add(_make_file("c1"))
        await repo.add(_make_file("c2"))
        assert await repo.count() == 2


# ── Prune Tests (parity with test_file_repository.py) ─────────────────────

class TestSqliteFileRepositoryPrune:

    @pytest.mark.asyncio
    async def test_prune_removes_old_completed_files(self, repo):
        old_time = datetime.now() - timedelta(days=30)
        await repo.add(_make_file("old", status=FileStatus.COMPLETED, completed_at=old_time, discovered_at=old_time))
        await repo.add(_make_file("new", status=FileStatus.COMPLETED, completed_at=datetime.now()))

        cutoff = datetime.now() - timedelta(days=7)
        pruned = await repo.prune_terminal_files({FileStatus.COMPLETED, FileStatus.FAILED}, cutoff)

        assert pruned == 1
        assert await repo.get_by_id("old") is None
        assert await repo.get_by_id("new") is not None

    @pytest.mark.asyncio
    async def test_prune_removes_old_failed_files(self, repo):
        old_time = datetime.now() - timedelta(days=30)
        await repo.add(_make_file("old-fail", status=FileStatus.FAILED, failed_at=old_time, discovered_at=old_time))

        cutoff = datetime.now() - timedelta(days=7)
        pruned = await repo.prune_terminal_files({FileStatus.COMPLETED, FileStatus.FAILED}, cutoff)
        assert pruned == 1

    @pytest.mark.asyncio
    async def test_prune_ignores_active_files(self, repo):
        old_time = datetime.now() - timedelta(days=30)
        await repo.add(_make_file("copying", status=FileStatus.COPYING, discovered_at=old_time))

        cutoff = datetime.now() - timedelta(days=7)
        pruned = await repo.prune_terminal_files({FileStatus.COMPLETED, FileStatus.FAILED}, cutoff)
        assert pruned == 0
        assert await repo.get_by_id("copying") is not None

    @pytest.mark.asyncio
    async def test_prune_uses_timestamp_fallback_chain(self, repo):
        """Tests fallback: completed_at → failed_at → space_error_at → discovered_at."""
        old_time = datetime.now() - timedelta(days=30)
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
    async def test_prune_uses_discovered_at_as_final_fallback(self, repo):
        old_time = datetime.now() - timedelta(days=30)
        await repo.add(_make_file("only-disc", status=FileStatus.FAILED, discovered_at=old_time))

        cutoff = datetime.now() - timedelta(days=7)
        pruned = await repo.prune_terminal_files({FileStatus.FAILED}, cutoff)
        assert pruned == 1

    @pytest.mark.asyncio
    async def test_prune_returns_zero_on_empty_repo(self, repo):
        cutoff = datetime.now() - timedelta(days=7)
        pruned = await repo.prune_terminal_files({FileStatus.COMPLETED}, cutoff)
        assert pruned == 0

    @pytest.mark.asyncio
    async def test_prune_respects_cutoff_boundary(self, repo):
        """File exactly at cutoff should NOT be pruned (must be strictly older)."""
        cutoff = datetime.now() - timedelta(days=7)
        await repo.add(_make_file("boundary", status=FileStatus.COMPLETED, completed_at=cutoff))
        pruned = await repo.prune_terminal_files({FileStatus.COMPLETED}, cutoff)
        assert pruned == 0

    @pytest.mark.asyncio
    async def test_prune_empty_states_set(self, repo):
        await repo.add(_make_file("f1", status=FileStatus.COMPLETED, completed_at=datetime.now() - timedelta(days=30)))
        pruned = await repo.prune_terminal_files(set(), datetime.now())
        assert pruned == 0


# ── SQLite-specific Tests ─────────────────────────────────────────────────

class TestSqliteSpecific:

    @pytest.mark.asyncio
    async def test_persistence_across_reconnect(self, tmp_path):
        """Data survives close + reopen."""
        db_path = str(tmp_path / "persist.db")

        # Write
        repo1 = SqliteFileRepository(db_path)
        await repo1.init_db(run_migrations=False)
        await repo1.create_schema()
        await repo1.add(_make_file("persist-1"))
        await repo1.close()

        # Read from fresh connection
        repo2 = SqliteFileRepository(db_path)
        await repo2.init_db(run_migrations=False)
        await repo2.create_schema()
        result = await repo2.get_by_id("persist-1")
        assert result is not None
        assert result.file_path == "/test/persist-1.mxf"
        await repo2.close()

    @pytest.mark.asyncio
    async def test_retry_info_serialization(self, repo):
        """RetryInfo survives round-trip through JSON serialization."""
        now = datetime.now()
        later = now + timedelta(minutes=5)
        retry = RetryInfo(
            scheduled_at=now,
            retry_at=later,
            reason="space shortage",
            retry_type="space",
        )
        f = _make_file("retry-test", retry_info=retry)
        await repo.add(f)

        result = await repo.get_by_id("retry-test")
        assert result.retry_info is not None
        assert result.retry_info.reason == "space shortage"
        assert result.retry_info.retry_type == "space"
        # Datetime precision may differ slightly due to ISO serialisation
        assert abs((result.retry_info.scheduled_at - now).total_seconds()) < 1
        assert abs((result.retry_info.retry_at - later).total_seconds()) < 1

    @pytest.mark.asyncio
    async def test_none_retry_info_round_trip(self, repo):
        """File with no RetryInfo loads as None, not empty object."""
        f = _make_file("no-retry")
        await repo.add(f)
        result = await repo.get_by_id("no-retry")
        assert result.retry_info is None

    @pytest.mark.asyncio
    async def test_all_datetime_fields_round_trip(self, repo):
        """All datetime fields survive serialisation."""
        now = datetime.now()
        f = _make_file(
            "dt-test",
            discovered_at=now,
            completed_at=now,
            failed_at=now,
            space_error_at=now,
            growth_stable_since=now,
        )
        f.started_copying_at = now
        f.creation_time = now
        f.last_write_time = now
        f.last_growth_check = now
        await repo.add(f)

        result = await repo.get_by_id("dt-test")
        # All datetimes should be within 1 second of original (ISO precision)
        for field in ["discovered_at", "completed_at", "failed_at", "space_error_at",
                      "growth_stable_since", "started_copying_at", "creation_time",
                      "last_write_time", "last_growth_check"]:
            original = getattr(f, field)
            loaded = getattr(result, field)
            assert loaded is not None, f"{field} should not be None"
            assert abs((loaded - original).total_seconds()) < 1, f"{field} datetime mismatch"

    @pytest.mark.asyncio
    async def test_all_numeric_fields_round_trip(self, repo):
        """All numeric/float fields survive serialisation."""
        f = _make_file(
            "num-test",
            file_size=1_073_741_824,
            copy_progress=67.5,
            bytes_copied=536_870_912,
            copy_speed_mbps=125.3,
            growth_rate_mbps=50.7,
            previous_file_size=500_000_000,
            first_seen_size=100_000_000,
        )
        f.retry_count = 3
        await repo.add(f)

        result = await repo.get_by_id("num-test")
        assert result.file_size == 1_073_741_824
        assert result.copy_progress == 67.5
        assert result.bytes_copied == 536_870_912
        assert abs(result.copy_speed_mbps - 125.3) < 0.01
        assert abs(result.growth_rate_mbps - 50.7) < 0.01
        assert result.previous_file_size == 500_000_000
        assert result.first_seen_size == 100_000_000
        assert result.retry_count == 3

    @pytest.mark.asyncio
    async def test_all_file_statuses_round_trip(self, repo):
        """Every FileStatus enum value survives serialisation."""
        for i, status in enumerate(FileStatus):
            f = _make_file(f"status-{i}", status=status)
            await repo.add(f)
            result = await repo.get_by_id(f"status-{i}")
            assert result.status == status, f"Status {status} did not round-trip"

    @pytest.mark.asyncio
    async def test_destination_path_and_error_message(self, repo):
        """Optional string fields survive round-trip."""
        f = _make_file("str-test", destination_path="/dest/file.mxf")
        f.error_message = "Network timeout after 30s"
        await repo.add(f)

        result = await repo.get_by_id("str-test")
        assert result.destination_path == "/dest/file.mxf"
        assert result.error_message == "Network timeout after 30s"

    @pytest.mark.asyncio
    async def test_null_optional_fields(self, repo):
        """Optional fields default to None."""
        f = _make_file("null-test")
        await repo.add(f)
        result = await repo.get_by_id("null-test")
        assert result.destination_path is None
        assert result.error_message is None
        assert result.completed_at is None
        assert result.failed_at is None
        assert result.space_error_at is None
        assert result.started_copying_at is None
        assert result.creation_time is None
        assert result.last_write_time is None
        assert result.last_growth_check is None
        assert result.growth_stable_since is None
        assert result.retry_info is None

    @pytest.mark.asyncio
    async def test_update_changes_all_fields(self, repo):
        """update() persists changes to every field."""
        f = _make_file("update-all")
        await repo.add(f)

        now = datetime.now()
        updated = f.model_copy(update={
            "status": FileStatus.COPYING,
            "file_size": 999,
            "copy_progress": 50.0,
            "bytes_copied": 500,
            "copy_speed_mbps": 100.0,
            "destination_path": "/dest/updated.mxf",
            "error_message": "some error",
            "retry_count": 2,
            "started_copying_at": now,
            "growth_rate_mbps": 10.0,
            "previous_file_size": 800,
            "first_seen_size": 200,
        })
        await repo.update(updated)

        result = await repo.get_by_id("update-all")
        assert result.status == FileStatus.COPYING
        assert result.file_size == 999
        assert result.copy_progress == 50.0
        assert result.bytes_copied == 500
        assert result.destination_path == "/dest/updated.mxf"
        assert result.error_message == "some error"
        assert result.retry_count == 2

    @pytest.mark.asyncio
    async def test_many_files_performance(self, repo):
        """Insert and retrieve 500 files — basic performance check."""
        for i in range(500):
            await repo.add(_make_file(f"perf-{i}"))

        assert await repo.count() == 500
        all_files = await repo.get_all()
        assert len(all_files) == 500

    @pytest.mark.asyncio
    async def test_init_db_creates_directory(self, tmp_path):
        """init_db() creates parent directories if they don't exist."""
        db_path = str(tmp_path / "sub" / "dir" / "test.db")
        r = SqliteFileRepository(db_path)
        await r.init_db(run_migrations=False)
        await r.create_schema()
        assert os.path.exists(db_path)
        await r.close()

    @pytest.mark.asyncio
    async def test_migrations_are_idempotent(self, tmp_path):
        """Running migrations multiple times doesn't fail."""
        db_path = str(tmp_path / "idempotent.db")
        r1 = SqliteFileRepository(db_path)
        await r1.init_db()
        await r1.add(_make_file("m1"))
        await r1.close()

        # Second init on same DB
        r2 = SqliteFileRepository(db_path)
        await r2.init_db()
        result = await r2.get_by_id("m1")
        assert result is not None
        await r2.close()


# ── Close & Lifecycle Tests ───────────────────────────────────────────────

class TestSqliteLifecycle:

    @pytest.mark.asyncio
    async def test_use_after_close_raises_runtime_error(self, tmp_path):
        """All public methods must raise RuntimeError after close()."""
        db_path = str(tmp_path / "closed.db")
        repo = SqliteFileRepository(db_path)
        await repo.init_db(run_migrations=False)
        await repo.create_schema()
        await repo.close()

        with pytest.raises(RuntimeError, match="not initialized"):
            await repo.get_by_id("any")
        with pytest.raises(RuntimeError, match="not initialized"):
            await repo.get_all()
        with pytest.raises(RuntimeError, match="not initialized"):
            await repo.add(_make_file("x"))
        with pytest.raises(RuntimeError, match="not initialized"):
            await repo.update(_make_file("x"))
        with pytest.raises(RuntimeError, match="not initialized"):
            await repo.remove("x")
        with pytest.raises(RuntimeError, match="not initialized"):
            await repo.count()
        with pytest.raises(RuntimeError, match="not initialized"):
            await repo.prune_terminal_files({FileStatus.COMPLETED}, datetime.now())

    @pytest.mark.asyncio
    async def test_use_before_init_raises_runtime_error(self):
        """Methods called before init_db() must raise RuntimeError."""
        repo = SqliteFileRepository("unused.db")
        with pytest.raises(RuntimeError, match="not initialized"):
            await repo.get_by_id("any")

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self, tmp_path):
        """Calling close() multiple times must not raise."""
        db_path = str(tmp_path / "idem.db")
        repo = SqliteFileRepository(db_path)
        await repo.init_db(run_migrations=False)
        await repo.create_schema()
        await repo.close()
        await repo.close()  # should not raise


# ── Concurrent Operations Tests ──────────────────────────────────────────

class TestSqliteConcurrency:

    @pytest.mark.asyncio
    async def test_concurrent_adds(self, repo):
        """Multiple concurrent add() calls must not lose data."""
        tasks = [repo.add(_make_file(f"conc-{i}")) for i in range(20)]
        await asyncio.gather(*tasks)
        assert await repo.count() == 20

    @pytest.mark.asyncio
    async def test_concurrent_reads_during_write(self, repo):
        """Reads must not fail while writes are happening."""
        await repo.add(_make_file("existing"))

        async def writer():
            for i in range(10):
                await repo.add(_make_file(f"w-{i}"))

        async def reader():
            for _ in range(10):
                await repo.get_all()

        await asyncio.gather(writer(), reader())
        assert await repo.count() == 11  # 1 existing + 10 written

    @pytest.mark.asyncio
    async def test_concurrent_updates(self, repo):
        """Concurrent update() calls must not corrupt data."""
        f = _make_file("upd-target")
        await repo.add(f)

        async def updater(progress: float):
            updated = f.model_copy(update={"copy_progress": progress})
            await repo.update(updated)

        tasks = [updater(float(i)) for i in range(10)]
        await asyncio.gather(*tasks)
        result = await repo.get_by_id("upd-target")
        assert result is not None
        # We don't know which update wins, but it must be one of them
        assert result.copy_progress in [float(i) for i in range(10)]
