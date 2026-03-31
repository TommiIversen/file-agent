"""
SQLite File Repository — persistent data access layer for TrackedFile objects.

Drop-in replacement for the in-memory FileRepository. Uses aiosqlite with
WAL journaling for concurrent reads during writes. All datetime values are
stored as ISO 8601 strings; RetryInfo is stored as JSON.

Write operations use BEGIN IMMEDIATE within an asyncio.Lock to serialize
transactions on the single connection, preventing SQLITE_BUSY errors.
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import aiosqlite

from app.models import FileStatus, RetryInfo, TrackedFile

# All datetime fields on TrackedFile
_DATETIME_FIELDS = frozenset({
    "discovered_at", "creation_time", "last_write_time",
    "started_copying_at", "completed_at", "failed_at",
    "space_error_at", "last_growth_check", "growth_stable_since",
})

# Column order used in INSERT — must match _tracked_file_to_row()
_COLUMNS = (
    "id", "file_path", "status", "file_size", "destination_path",
    "copy_progress", "bytes_copied", "copy_speed_mbps",
    "error_message", "retry_count", "retry_info",
    "discovered_at", "creation_time", "last_write_time",
    "started_copying_at", "completed_at", "failed_at",
    "space_error_at", "last_growth_check",
    "growth_rate_mbps", "previous_file_size", "first_seen_size",
    "growth_stable_since",
)

_PLACEHOLDERS = ", ".join("?" for _ in _COLUMNS)
_COL_LIST = ", ".join(_COLUMNS)
_UPDATE_SET = ", ".join(f"{c} = ?" for c in _COLUMNS if c != "id")


class SqliteFileRepository:
    """
    Persistent SQLite‐backed repository for TrackedFile objects.

    Implements the same interface as the in-memory FileRepository so it
    can be swapped in via dependencies.py without touching any domain code.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None
        self._write_lock = asyncio.Lock()

    @property
    def connection(self) -> aiosqlite.Connection:
        """Expose the open DB connection for shared use (e.g. SqliteEventStore)."""
        return self._ensure_db()

    @property
    def write_lock(self) -> asyncio.Lock:
        """Expose the write lock for shared use by other stores on the same DB."""
        return self._write_lock

    def _ensure_db(self) -> aiosqlite.Connection:
        """Return the open DB connection, or raise if not initialized."""
        if self._db is None:
            raise RuntimeError("Database not initialized — call init_db() first")
        return self._db

    async def init_db(self, *, run_migrations: bool = True) -> None:
        """
        Open the database connection, enable WAL mode, and optionally run
        Alembic migrations.

        Args:
            run_migrations: If True (default), run Alembic migrations.
                Set to False in tests to use create_schema() instead.
        """
        # Ensure the parent directory exists
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        # isolation_level=None disables implicit transactions so we can
        # use explicit BEGIN IMMEDIATE for write serialization.
        self._db = await aiosqlite.connect(self._db_path, isolation_level=None)
        self._db.row_factory = aiosqlite.Row

        # Performance & safety pragmas
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.execute("PRAGMA busy_timeout=5000")

        if run_migrations:
            await self._run_migrations()

        logging.info("SqliteFileRepository initialized (WAL mode) at %s", self._db_path)

    async def create_schema(self) -> None:
        """
        Create tables directly with SQL — fast alternative to Alembic for tests.
        Must be called after init_db(run_migrations=False).
        """
        db = self._ensure_db()
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS tracked_files (
                id TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Discovered',
                file_size INTEGER NOT NULL DEFAULT 0,
                destination_path TEXT,
                copy_progress REAL NOT NULL DEFAULT 0.0,
                bytes_copied INTEGER NOT NULL DEFAULT 0,
                copy_speed_mbps REAL NOT NULL DEFAULT 0.0,
                error_message TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                retry_info TEXT,
                discovered_at TEXT NOT NULL,
                creation_time TEXT,
                last_write_time TEXT,
                started_copying_at TEXT,
                completed_at TEXT,
                failed_at TEXT,
                space_error_at TEXT,
                last_growth_check TEXT,
                growth_rate_mbps REAL NOT NULL DEFAULT 0.0,
                previous_file_size INTEGER NOT NULL DEFAULT 0,
                first_seen_size INTEGER NOT NULL DEFAULT 0,
                growth_stable_since TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_tracked_files_file_path ON tracked_files(file_path);
            CREATE INDEX IF NOT EXISTS ix_tracked_files_status ON tracked_files(status);
            CREATE INDEX IF NOT EXISTS ix_tracked_files_discovered_at ON tracked_files(discovered_at);
            CREATE INDEX IF NOT EXISTS ix_tracked_files_completed_at ON tracked_files(completed_at);

            CREATE TABLE IF NOT EXISTS system_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                context TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_system_events_timestamp ON system_events(timestamp);
            CREATE INDEX IF NOT EXISTS ix_system_events_level ON system_events(level);
            CREATE INDEX IF NOT EXISTS ix_system_events_event_type ON system_events(event_type);
        """)

    async def _run_migrations(self) -> None:
        """Run pending Alembic migrations against the open connection."""
        import asyncio
        from alembic.config import Config
        from alembic import command

        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option(
            "sqlalchemy.url",
            f"sqlite+aiosqlite:///{self._db_path}",
        )
        # Alembic's command API is synchronous — run in a thread
        await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
        logging.info("Alembic migrations applied successfully")

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None
            logging.info("SqliteFileRepository connection closed")

    # ------------------------------------------------------------------
    # Public interface (matches FileRepository / FileRepositoryProtocol)
    # ------------------------------------------------------------------

    async def get_by_id(self, file_id: str) -> Optional[TrackedFile]:
        """Get a single tracked file by its unique ID."""
        db = self._ensure_db()
        async with db.execute(
            "SELECT * FROM tracked_files WHERE id = ?", (file_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return self._row_to_tracked_file(row) if row else None

    async def get_all(self) -> List[TrackedFile]:
        """Get a list of all tracked files."""
        db = self._ensure_db()
        async with db.execute("SELECT * FROM tracked_files") as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_tracked_file(r) for r in rows]

    async def add(self, tracked_file: TrackedFile) -> None:
        """Add a new tracked file to the repository. Duplicates are silently ignored."""
        db = self._ensure_db()
        values = self._tracked_file_to_row(tracked_file)
        async with self._write_lock:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    f"INSERT OR IGNORE INTO tracked_files ({_COL_LIST}) VALUES ({_PLACEHOLDERS})",
                    values,
                )
                await db.commit()
                if cursor.rowcount == 0:
                    logging.error(
                        "File with ID %s already exists in repository. Use update() to modify.",
                        tracked_file.id,
                    )
            except Exception:
                await db.rollback()
                raise

    async def update(self, tracked_file: TrackedFile) -> None:
        """Update an existing tracked file in the repository."""
        db = self._ensure_db()
        values = self._tracked_file_to_row(tracked_file)
        # values[0] is id — move it to end for the WHERE clause
        update_values = list(values[1:]) + [values[0]]
        async with self._write_lock:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    f"UPDATE tracked_files SET {_UPDATE_SET} WHERE id = ?",
                    update_values,
                )
                await db.commit()
                if cursor.rowcount == 0:
                    logging.warning(
                        "File with ID %s does not exist in repository. Cannot update.",
                        tracked_file.id,
                    )
            except Exception:
                await db.rollback()
                raise

    async def remove(self, file_id: str) -> bool:
        """Remove a tracked file from the repository by its ID."""
        db = self._ensure_db()
        async with self._write_lock:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    "DELETE FROM tracked_files WHERE id = ?", (file_id,)
                )
                await db.commit()
                return cursor.rowcount > 0
            except Exception:
                await db.rollback()
                raise

    async def count(self) -> int:
        """Return the total number of files in the repository."""
        db = self._ensure_db()
        async with db.execute("SELECT COUNT(*) FROM tracked_files") as cursor:
            row = await cursor.fetchone()
            return row[0]

    async def prune_terminal_files(
        self,
        terminal_states: Set[FileStatus],
        cutoff_date: datetime,
    ) -> int:
        """
        Delete files in a terminal state whose last activity timestamp is
        strictly before cutoff_date.

        The "last activity" falls back through:
          completed_at → failed_at → space_error_at → discovered_at

        Note: SQL IN (...) is order-independent, so set iteration order is safe.
        """
        db = self._ensure_db()
        if not terminal_states:
            return 0

        placeholders = ", ".join("?" for _ in terminal_states)
        cutoff_iso = cutoff_date.isoformat()
        state_values = [s.value for s in terminal_states]

        sql = f"""
            DELETE FROM tracked_files
            WHERE status IN ({placeholders})
              AND COALESCE(completed_at, failed_at, space_error_at, discovered_at) < ?
        """
        async with self._write_lock:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(sql, state_values + [cutoff_iso])
                await db.commit()
                return cursor.rowcount
            except Exception:
                await db.rollback()
                raise

    # ------------------------------------------------------------------
    # Mapping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_tracked_file(row: aiosqlite.Row) -> TrackedFile:
        """Convert a database row to a TrackedFile Pydantic model."""
        data: Dict[str, Any] = dict(row)

        # Parse datetime strings back to datetime objects
        for field in _DATETIME_FIELDS:
            raw = data.get(field)
            if raw is not None:
                data[field] = datetime.fromisoformat(raw)

        # Parse status string back to enum
        data["status"] = FileStatus(data["status"])

        # Parse retry_info JSON
        retry_raw = data.get("retry_info")
        if retry_raw is not None:
            data["retry_info"] = RetryInfo(**json.loads(retry_raw))

        return TrackedFile(**data)

    @staticmethod
    def _tracked_file_to_row(tf: TrackedFile) -> tuple:
        """Convert a TrackedFile to a tuple of values matching _COLUMNS order."""
        def _dt(val: Optional[datetime]) -> Optional[str]:
            return val.isoformat() if val is not None else None

        def _retry(val: Optional[RetryInfo]) -> Optional[str]:
            return json.dumps(val.model_dump(), default=str) if val is not None else None

        return (
            tf.id,
            tf.file_path,
            tf.status.value,
            tf.file_size,
            tf.destination_path,
            tf.copy_progress,
            tf.bytes_copied,
            tf.copy_speed_mbps,
            tf.error_message,
            tf.retry_count,
            _retry(tf.retry_info),
            _dt(tf.discovered_at),
            _dt(tf.creation_time),
            _dt(tf.last_write_time),
            _dt(tf.started_copying_at),
            _dt(tf.completed_at),
            _dt(tf.failed_at),
            _dt(tf.space_error_at),
            _dt(tf.last_growth_check),
            tf.growth_rate_mbps,
            tf.previous_file_size,
            tf.first_seen_size,
            _dt(tf.growth_stable_since),
        )
