"""
Tests for SqliteEventStore — persistent storage for system events.

Tests cover CRUD operations, filtering, pruning, and integration
with GlobalEventLogger (write-through + rehydration).
"""

import asyncio
import pytest
from datetime import datetime, timedelta, timezone

from app.core.sqlite_file_repository import SqliteFileRepository
from app.core.sqlite_event_store import SqliteEventStore
from app.core.global_event_logger import GlobalEventLogger, LoggedEvent


def _make_event(
    event_type: str = "TestEvent",
    message: str = "Test message",
    level: str = "INFO",
    timestamp: datetime = None,
    context: dict = None,
) -> LoggedEvent:
    return LoggedEvent(
        timestamp=timestamp or datetime.now(timezone.utc),
        event_type=event_type,
        message=message,
        level=level,
        context=context,
    )


@pytest.fixture
async def db_repo(tmp_path):
    """Create a fresh SqliteFileRepository with schema (shared DB for event store)."""
    db_path = str(tmp_path / "test.db")
    repo = SqliteFileRepository(db_path)
    await repo.init_db(run_migrations=False)
    await repo.create_schema()
    yield repo
    await repo.close()


@pytest.fixture
async def store(db_repo):
    """Create a SqliteEventStore using the shared DB connection."""
    return SqliteEventStore(db=db_repo.connection, write_lock=db_repo.write_lock)


# ── Basic CRUD Tests ─────────────────────────────────────────────────────

class TestSqliteEventStoreCRUD:

    @pytest.mark.asyncio
    async def test_add_and_get_event(self, store):
        event = _make_event(message="Hello world")
        await store.add_event(event)
        events = await store.get_events(limit=10)
        assert len(events) == 1
        assert events[0].message == "Hello world"
        assert events[0].event_type == "TestEvent"
        assert events[0].level == "INFO"

    @pytest.mark.asyncio
    async def test_get_events_newest_first(self, store):
        e1 = _make_event(message="First", timestamp=datetime(2026, 1, 1, 10, 0))
        e2 = _make_event(message="Second", timestamp=datetime(2026, 1, 1, 11, 0))
        e3 = _make_event(message="Third", timestamp=datetime(2026, 1, 1, 12, 0))
        await store.add_event(e1)
        await store.add_event(e2)
        await store.add_event(e3)

        events = await store.get_events()
        assert events[0].message == "Third"
        assert events[1].message == "Second"
        assert events[2].message == "First"

    @pytest.mark.asyncio
    async def test_get_events_with_limit(self, store):
        for i in range(10):
            await store.add_event(_make_event(message=f"Event {i}"))
        events = await store.get_events(limit=3)
        assert len(events) == 3

    @pytest.mark.asyncio
    async def test_get_events_empty(self, store):
        events = await store.get_events()
        assert events == []

    @pytest.mark.asyncio
    async def test_context_round_trip(self, store):
        event = _make_event(
            context={"file_path": "/test/file.mxf", "retry_count": 3}
        )
        await store.add_event(event)
        events = await store.get_events()
        assert events[0].context == {"file_path": "/test/file.mxf", "retry_count": 3}

    @pytest.mark.asyncio
    async def test_null_context_round_trip(self, store):
        event = _make_event(context=None)
        await store.add_event(event)
        events = await store.get_events()
        assert events[0].context is None

    @pytest.mark.asyncio
    async def test_datetime_precision(self, store):
        now = datetime.now(timezone.utc)
        event = _make_event(timestamp=now)
        await store.add_event(event)
        events = await store.get_events()
        assert abs((events[0].timestamp - now).total_seconds()) < 1


# ── Filter Tests ─────────────────────────────────────────────────────────

class TestSqliteEventStoreFilters:

    @pytest.mark.asyncio
    async def test_filter_by_level(self, store):
        await store.add_event(_make_event(level="INFO", message="info"))
        await store.add_event(_make_event(level="WARNING", message="warn"))
        await store.add_event(_make_event(level="ERROR", message="err"))

        info = await store.get_events(level="INFO")
        assert len(info) == 1
        assert info[0].message == "info"

        errors = await store.get_events(level="ERROR")
        assert len(errors) == 1
        assert errors[0].message == "err"

    @pytest.mark.asyncio
    async def test_filter_by_level_case_insensitive(self, store):
        await store.add_event(_make_event(level="INFO"))
        # SqliteEventStore normalizes to uppercase
        events = await store.get_events(level="info")
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_filter_by_from_date(self, store):
        old = _make_event(timestamp=datetime(2026, 1, 1), message="old")
        recent = _make_event(timestamp=datetime(2026, 3, 15), message="recent")
        await store.add_event(old)
        await store.add_event(recent)

        events = await store.get_events(from_date=datetime(2026, 3, 1))
        assert len(events) == 1
        assert events[0].message == "recent"

    @pytest.mark.asyncio
    async def test_filter_combined_level_and_from_date(self, store):
        await store.add_event(_make_event(
            level="ERROR", timestamp=datetime(2026, 1, 1), message="old error"
        ))
        await store.add_event(_make_event(
            level="ERROR", timestamp=datetime(2026, 3, 15), message="recent error"
        ))
        await store.add_event(_make_event(
            level="INFO", timestamp=datetime(2026, 3, 15), message="recent info"
        ))

        events = await store.get_events(level="ERROR", from_date=datetime(2026, 3, 1))
        assert len(events) == 1
        assert events[0].message == "recent error"

    @pytest.mark.asyncio
    async def test_get_count(self, store):
        assert await store.get_count() == 0
        await store.add_event(_make_event(level="INFO"))
        await store.add_event(_make_event(level="ERROR"))
        await store.add_event(_make_event(level="INFO"))
        assert await store.get_count() == 3
        assert await store.get_count(level="INFO") == 2
        assert await store.get_count(level="ERROR") == 1


# ── Prune Tests ──────────────────────────────────────────────────────────

class TestSqliteEventStorePrune:

    @pytest.mark.asyncio
    async def test_prune_removes_old_events(self, store):
        old = _make_event(timestamp=datetime.now(timezone.utc) - timedelta(days=60))
        recent = _make_event(timestamp=datetime.now(timezone.utc))
        await store.add_event(old)
        await store.add_event(recent)

        pruned = await store.prune_old_events(days=30)
        assert pruned == 1
        remaining = await store.get_events()
        assert len(remaining) == 1
        assert remaining[0].timestamp > datetime.now(timezone.utc) - timedelta(days=1)

    @pytest.mark.asyncio
    async def test_prune_returns_zero_when_nothing_to_prune(self, store):
        await store.add_event(_make_event(timestamp=datetime.now(timezone.utc)))
        pruned = await store.prune_old_events(days=30)
        assert pruned == 0

    @pytest.mark.asyncio
    async def test_prune_empty_store(self, store):
        pruned = await store.prune_old_events(days=30)
        assert pruned == 0


# ── GlobalEventLogger Integration Tests ──────────────────────────────────

class TestGlobalEventLoggerIntegration:

    @pytest.mark.asyncio
    async def test_write_through_persists_events(self, store):
        """Events added via GlobalEventLogger are persisted to SQLite."""
        logger = GlobalEventLogger()
        logger.set_event_store(store)

        # Simulate an event via _add_log (needs a DomainEvent-like object)
        from unittest.mock import MagicMock
        mock_event = MagicMock()
        mock_event.timestamp = datetime.now(timezone.utc)
        type(mock_event).__name__ = "FileStatusChangedEvent"

        await logger._add_log(mock_event, "File completed", "INFO", {"file_id": "f1"})

        # Check SQLite
        db_events = await store.get_events()
        assert len(db_events) == 1
        assert db_events[0].message == "File completed"
        assert db_events[0].context == {"file_id": "f1"}

    @pytest.mark.asyncio
    async def test_get_events_reads_from_db(self, store):
        """get_events() queries SQLite directly."""
        logger = GlobalEventLogger()
        logger.set_event_store(store)

        from unittest.mock import MagicMock
        mock_event = MagicMock()
        mock_event.timestamp = datetime.now(timezone.utc)
        type(mock_event).__name__ = "TestEvent"

        await logger._add_log(mock_event, "Persisted test", "INFO")

        events = await logger.get_events(limit=10)
        assert len(events) == 1
        assert events[0].message == "Persisted test"

    @pytest.mark.asyncio
    async def test_get_events_with_from_date(self, store):
        """get_events() filters by from_date via SQLite."""
        await store.add_event(_make_event(
            message="Old event", timestamp=datetime(2026, 1, 1)
        ))
        await store.add_event(_make_event(
            message="Recent event", timestamp=datetime(2026, 3, 20)
        ))

        logger = GlobalEventLogger()
        logger.set_event_store(store)

        events = await logger.get_events(from_date=datetime(2026, 3, 1))
        assert len(events) == 1
        assert events[0].message == "Recent event"

    @pytest.mark.asyncio
    async def test_get_events_without_store_returns_empty(self):
        """get_events() returns empty list when no store is attached."""
        logger = GlobalEventLogger()
        events = await logger.get_events()
        assert events == []

    @pytest.mark.asyncio
    async def test_get_events_with_limit(self, store):
        """get_events() respects limit parameter."""
        for i in range(10):
            await store.add_event(_make_event(message=f"Event {i}"))

        logger = GlobalEventLogger()
        logger.set_event_store(store)

        events = await logger.get_events(limit=3)
        assert len(events) == 3


# ── Concurrent Access Tests ──────────────────────────────────────────────

class TestSqliteEventStoreConcurrency:

    @pytest.mark.asyncio
    async def test_concurrent_adds(self, store):
        """Multiple concurrent add_event() calls must not lose data."""
        tasks = [
            store.add_event(_make_event(message=f"Concurrent {i}"))
            for i in range(20)
        ]
        await asyncio.gather(*tasks)
        assert await store.get_count() == 20

    @pytest.mark.asyncio
    async def test_concurrent_reads_during_writes(self, store):
        """Reads must not fail while writes are happening."""
        await store.add_event(_make_event(message="Existing"))

        async def writer():
            for i in range(10):
                await store.add_event(_make_event(message=f"Write {i}"))

        async def reader():
            for _ in range(10):
                await store.get_events()

        await asyncio.gather(writer(), reader())
        assert await store.get_count() == 11
