"""
UserSettingsService — persistent user-facing settings backed by SQLite.

Shares the same database connection as SqliteFileRepository / SqliteEventStore.
Provides typed get/set operations for the 12 user-editable settings.

Settings priority: hardcoded defaults → DB values.
Env-file migration runs once at init (B1b): if DB has default value and env
has a different value, the env value is written to DB.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from app.config import Settings

logger = logging.getLogger(__name__)

# The 12 user-editable settings with their types and defaults.
# key → (type, default_value)
USER_SETTINGS_SCHEMA: dict[str, tuple[type, Any]] = {
    "source_directory": (str, ""),
    "destination_directory": (str, ""),
    "network_share_url": (str, ""),
    "enable_auto_mount": (bool, False),
    "macos_mount_point": (str, ""),
    "tally_light_switch_ip": (str, ""),
    "output_folder_template_enabled": (bool, False),
    "output_folder_rules": (str, ""),
    "output_folder_default_category": (str, "OTHER"),
    "output_folder_date_format": (str, "filename[0:6]"),
    "output_folder_time_format": (str, "filename[7:13]"),
    "max_concurrent_copies": (int, 7),
    "justin_auto_stop_minutes": (int, 0),
    "brand_name": (str, "Dr. Feta"),
}

# Settings that require an app restart to take effect.
REQUIRES_RESTART: frozenset[str] = frozenset()


def _serialize(value: Any) -> str:
    """Serialize a Python value to its DB string representation."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _deserialize(raw: str, expected_type: type) -> Any:
    """Deserialize a DB string to the expected Python type."""
    if expected_type is bool:
        return raw.lower() in ("true", "1", "yes")
    if expected_type is int:
        return int(raw)
    return raw


_UPSERT_SQL = (
    "INSERT INTO user_settings (key, value, updated_at) "
    "VALUES (?, ?, ?) "
    "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at"
)


class UserSettingsService:
    """
    Persistent service for the 12 user-editable settings.

    Shares a DB connection + write lock from SqliteFileRepository.
    """

    def __init__(self, db: aiosqlite.Connection, write_lock: asyncio.Lock) -> None:
        self._db = db
        self._write_lock = write_lock
        self._cache: dict[str, Any] = {}

    async def init(self, env_settings: Settings | None = None) -> None:
        """
        Load settings from DB into cache.
        If env_settings is provided, run one-time env → DB migration (B1b),
        then sync DB values back into the Settings singleton.
        """
        await self._load_cache()

        if env_settings is not None:
            await self._migrate_from_env(env_settings)
            self.sync_to_settings(env_settings)

        logger.info("UserSettingsService initialized (%d settings loaded)", len(self._cache))

    async def _load_cache(self) -> None:
        """Load all user_settings rows into the in-memory cache."""
        cursor = await self._db.execute("SELECT key, value FROM user_settings")
        rows = await cursor.fetchall()
        for row in rows:
            key = row[0]
            if key in USER_SETTINGS_SCHEMA:
                expected_type, default = USER_SETTINGS_SCHEMA[key]
                try:
                    self._cache[key] = _deserialize(row[1], expected_type)
                except (ValueError, TypeError):
                    logger.warning("Corrupt value for setting '%s', using default", key)
                    self._cache[key] = default

        # Fill any missing keys with defaults (e.g. fresh DB without migration seed)
        for key, (_, default) in USER_SETTINGS_SCHEMA.items():
            if key not in self._cache:
                self._cache[key] = default

    async def _migrate_from_env(self, env_settings: Settings) -> None:
        """
        One-time migration (B1b): if DB has the default value and env has
        a different value, copy the env value into DB.
        """
        migrated: list[str] = []
        for key, (expected_type, default) in USER_SETTINGS_SCHEMA.items():
            env_value = getattr(env_settings, key, None)
            if env_value is None:
                continue

            # Cast env value to expected type for comparison
            if expected_type is bool and isinstance(env_value, str):
                env_value = env_value.lower() in ("true", "1", "yes")
            elif expected_type is int and isinstance(env_value, str):
                env_value = int(env_value)

            current = self._cache.get(key, default)
            if current == default and env_value != default:
                await self._write_setting(key, env_value)
                self._cache[key] = env_value
                migrated.append(key)

        if migrated:
            logger.info("Migrated %d settings from env to database: %s",
                        len(migrated), ", ".join(migrated))

    def get(self, key: str) -> Any:
        """Get a setting value (from cache). Raises KeyError for unknown keys."""
        if key not in USER_SETTINGS_SCHEMA:
            raise KeyError(f"Unknown user setting: {key}")
        return self._cache.get(key, USER_SETTINGS_SCHEMA[key][1])

    def get_all(self) -> dict[str, Any]:
        """Get all 12 user settings as a dict."""
        return {
            key: self._cache.get(key, default)
            for key, (_, default) in USER_SETTINGS_SCHEMA.items()
        }

    def sync_to_settings(self, target: Settings) -> list[str]:
        """
        Write all cached DB values into the Settings singleton so the rest of
        the app sees DB-backed values.  Returns list of keys that were changed.
        """
        changed: list[str] = []
        for key, value in self.get_all().items():
            if hasattr(target, key) and getattr(target, key) != value:
                object.__setattr__(target, key, value)
                changed.append(key)
        if changed:
            logger.info("Synced %d DB settings into Settings: %s",
                        len(changed), ", ".join(changed))
        return changed

    def get_all_with_metadata(self) -> list[dict[str, Any]]:
        """Get all settings with type/default/restart metadata for the API."""
        result = []
        for key, (expected_type, default) in USER_SETTINGS_SCHEMA.items():
            result.append({
                "key": key,
                "value": self._cache.get(key, default),
                "type": expected_type.__name__,
                "default": default,
                "requires_restart": key in REQUIRES_RESTART,
            })
        return result

    async def set(self, key: str, value: Any) -> bool:
        """
        Set a single setting. Returns True if the value changed.
        Raises KeyError for unknown keys, ValueError for type mismatch.
        """
        if key not in USER_SETTINGS_SCHEMA:
            raise KeyError(f"Unknown user setting: {key}")

        expected_type, _ = USER_SETTINGS_SCHEMA[key]
        value = self._coerce(key, value, expected_type)

        old = self._cache.get(key)
        if old == value:
            return False

        await self._write_setting(key, value)
        self._cache[key] = value
        return True

    async def set_many(self, updates: dict[str, Any]) -> dict[str, bool]:
        """
        Set multiple settings atomically. Returns {key: changed} for each key.
        Validates all keys/values first, then writes in one transaction.
        Raises KeyError/ValueError on first invalid key/value.
        """
        # Phase 1: validate and coerce all values
        coerced: list[tuple[str, Any]] = []
        for key, value in updates.items():
            if key not in USER_SETTINGS_SCHEMA:
                raise KeyError(f"Unknown user setting: {key}")
            expected_type, _ = USER_SETTINGS_SCHEMA[key]
            coerced.append((key, self._coerce(key, value, expected_type)))

        # Phase 2: write all changes in one transaction
        now = datetime.now(timezone.utc).isoformat()
        results: dict[str, bool] = {}
        pending_cache: dict[str, Any] = {}
        async with self._write_lock:
            await self._db.execute("BEGIN IMMEDIATE")
            try:
                for key, value in coerced:
                    old = self._cache.get(key)
                    if old == value:
                        results[key] = False
                        continue
                    serialized = _serialize(value)
                    await self._db.execute(
                        _UPSERT_SQL,
                        (key, serialized, now),
                    )
                    pending_cache[key] = value
                    results[key] = True
                await self._db.commit()
            except Exception:
                await self._db.rollback()
                raise
        # Apply cache updates only after successful commit
        self._cache.update(pending_cache)
        return results

    def _coerce(self, key: str, value: Any, expected_type: type) -> Any:
        """Coerce a value to the expected type, raising ValueError on failure."""
        if expected_type is bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes")
            raise ValueError(f"Setting '{key}' expects bool, got {type(value).__name__}")
        if expected_type is int:
            try:
                return int(value)
            except (TypeError, ValueError):
                raise ValueError(f"Setting '{key}' expects int, got {type(value).__name__}")
        if expected_type is str:
            return str(value)
        raise ValueError(f"Unsupported type {expected_type} for setting '{key}'")

    async def _write_setting(self, key: str, value: Any) -> None:
        """Write a single setting to the DB."""
        now = datetime.now(timezone.utc).isoformat()
        serialized = _serialize(value)
        async with self._write_lock:
            await self._db.execute("BEGIN IMMEDIATE")
            try:
                await self._db.execute(
                    _UPSERT_SQL,
                    (key, serialized, now),
                )
                await self._db.commit()
            except Exception:
                await self._db.rollback()
                raise
