"""
SqliteEventStore — persistent storage for system events (LoggedEvent).

Shares the same SQLite database as SqliteFileRepository. Provides
write-through persistence and query capabilities for the GlobalEventLogger.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import aiosqlite

from app.core.global_event_logger import LoggedEvent


class SqliteEventStore:
    """
    Persistent SQLite-backed store for system events.

    Receives a shared aiosqlite connection (from SqliteFileRepository)
    and provides INSERT / SELECT / prune operations.
    """

    def __init__(self, db: aiosqlite.Connection, write_lock: asyncio.Lock) -> None:
        self._db = db
        self._write_lock = write_lock

    async def add_event(self, event: LoggedEvent) -> None:
        """Persist a single LoggedEvent to SQLite."""
        context_json = json.dumps(event.context) if event.context else None
        async with self._write_lock:
            await self._db.execute("BEGIN IMMEDIATE")
            try:
                await self._db.execute(
                    "INSERT INTO system_events (timestamp, event_type, level, message, context) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        event.timestamp.isoformat(),
                        event.event_type,
                        event.level,
                        event.message,
                        context_json,
                    ),
                )
                await self._db.commit()
            except Exception:
                await self._db.rollback()
                raise

    async def get_events(
        self,
        limit: Optional[int] = None,
        level: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        before_id: Optional[int] = None,
    ) -> List[LoggedEvent]:
        """
        Query events from SQLite with optional filters.

        Results are returned newest-first (descending id).
        Use before_id for cursor-based pagination (fetch events older than this id).
        Use from_date + to_date together to query a single day.
        """
        clauses: list[str] = []
        params: list = []

        if level:
            clauses.append("level = ?")
            params.append(level.upper())

        if from_date:
            clauses.append("timestamp >= ?")
            params.append(from_date.isoformat())

        if to_date:
            clauses.append("timestamp <= ?")
            params.append(to_date.isoformat())

        if before_id is not None:
            clauses.append("id < ?")
            params.append(before_id)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM system_events{where} ORDER BY id DESC"

        if limit:
            sql += " LIMIT ?"
            params.append(limit)

        async with self._db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_event(row) for row in rows]

    async def get_count(
        self,
        level: Optional[str] = None,
    ) -> int:
        """Return the total number of events, optionally filtered by level."""
        if level:
            async with self._db.execute(
                "SELECT COUNT(*) FROM system_events WHERE level = ?", (level.upper(),)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0
        else:
            async with self._db.execute("SELECT COUNT(*) FROM system_events") as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def prune_old_events(self, days: int = 30) -> int:
        """Delete events older than `days` days. Returns number of deleted rows."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        async with self._write_lock:
            await self._db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await self._db.execute(
                    "DELETE FROM system_events WHERE timestamp < ?", (cutoff,)
                )
                await self._db.commit()
                return cursor.rowcount
            except Exception:
                await self._db.rollback()
                raise

    @staticmethod
    def _row_to_event(row: aiosqlite.Row) -> LoggedEvent:
        """Convert a database row to a LoggedEvent."""
        context_raw = row["context"]
        context = json.loads(context_raw) if context_raw else None
        ts = datetime.fromisoformat(row["timestamp"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return LoggedEvent(
            timestamp=ts,
            event_type=row["event_type"],
            message=row["message"],
            level=row["level"],
            context=context,
            id=row["id"],
        )
