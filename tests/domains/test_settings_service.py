"""Tests for UserSettingsService — DB-backed user settings."""
import asyncio
import pytest
from unittest.mock import MagicMock

import aiosqlite

from app.domains.shared.settings_service import (
    UserSettingsService,
    USER_SETTINGS_SCHEMA,
    REQUIRES_RESTART,
    _serialize,
    _deserialize,
)


@pytest.fixture
async def db():
    """In-memory SQLite with user_settings table."""
    conn = await aiosqlite.connect(":memory:", isolation_level=None)
    await conn.execute("""
        CREATE TABLE user_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    yield conn
    await conn.close()


@pytest.fixture
async def service(db):
    """UserSettingsService backed by in-memory DB."""
    lock = asyncio.Lock()
    svc = UserSettingsService(db=db, write_lock=lock)
    await svc.init()
    return svc


class TestSerializationHelpers:

    def test_serialize_bool_true(self):
        assert _serialize(True) == "true"

    def test_serialize_bool_false(self):
        assert _serialize(False) == "false"

    def test_serialize_int(self):
        assert _serialize(7) == "7"

    def test_serialize_str(self):
        assert _serialize("hello") == "hello"

    def test_deserialize_bool_true(self):
        assert _deserialize("true", bool) is True

    def test_deserialize_bool_false(self):
        assert _deserialize("false", bool) is False

    def test_deserialize_int(self):
        assert _deserialize("42", int) == 42

    def test_deserialize_str(self):
        assert _deserialize("hello", str) == "hello"


class TestUserSettingsServiceInit:

    async def test_init_loads_defaults_when_db_empty(self, service):
        """Empty DB → all settings have their schema defaults."""
        all_settings = service.get_all()
        assert len(all_settings) == len(USER_SETTINGS_SCHEMA)
        for key, (_, default) in USER_SETTINGS_SCHEMA.items():
            assert all_settings[key] == default

    async def test_init_loads_existing_db_values(self, db):
        """Pre-populated DB values are loaded into cache."""
        await db.execute(
            "INSERT INTO user_settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("source_directory", "/my/source", "2026-04-08T00:00:00+00:00"),
        )
        lock = asyncio.Lock()
        svc = UserSettingsService(db=db, write_lock=lock)
        await svc.init()
        assert svc.get("source_directory") == "/my/source"

    async def test_init_corrupt_int_falls_back_to_default(self, db):
        """Corrupt DB value for int setting falls back to schema default."""
        await db.execute(
            "INSERT INTO user_settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("max_concurrent_copies", "not_a_number", "2026-04-08T00:00:00+00:00"),
        )
        lock = asyncio.Lock()
        svc = UserSettingsService(db=db, write_lock=lock)
        await svc.init()
        assert svc.get("max_concurrent_copies") == 7  # schema default


class TestGetAndSet:

    async def test_get_returns_default(self, service):
        assert service.get("max_concurrent_copies") == 7

    async def test_get_unknown_key_raises(self, service):
        with pytest.raises(KeyError, match="Unknown user setting"):
            service.get("nonexistent_key")

    async def test_set_and_get(self, service):
        changed = await service.set("source_directory", "/new/path")
        assert changed is True
        assert service.get("source_directory") == "/new/path"

    async def test_set_same_value_returns_false(self, service):
        await service.set("max_concurrent_copies", 7)
        changed = await service.set("max_concurrent_copies", 7)
        assert changed is False

    async def test_set_unknown_key_raises(self, service):
        with pytest.raises(KeyError, match="Unknown user setting"):
            await service.set("bad_key", "value")

    async def test_set_invalid_type_raises(self, service):
        with pytest.raises(ValueError, match="expects int"):
            await service.set("max_concurrent_copies", "not_a_number")

    async def test_set_persists_to_db(self, service, db):
        await service.set("destination_directory", "/dest")
        cursor = await db.execute(
            "SELECT value FROM user_settings WHERE key = ?", ("destination_directory",)
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "/dest"

    async def test_set_bool_from_string(self, service):
        changed = await service.set("enable_auto_mount", "true")
        assert changed is True
        assert service.get("enable_auto_mount") is True

    async def test_set_int_from_string(self, service):
        changed = await service.set("max_concurrent_copies", "12")
        assert changed is True
        assert service.get("max_concurrent_copies") == 12

    async def test_sync_to_settings_updates_target(self, service):
        await service.set("source_directory", "/synced")
        mock_settings = MagicMock()
        mock_settings.source_directory = ""
        changed = service.sync_to_settings(mock_settings)
        assert "source_directory" in changed
        assert mock_settings.source_directory == "/synced"


class TestSetMany:

    async def test_set_many_updates_multiple(self, service):
        results = await service.set_many({
            "source_directory": "/src",
            "destination_directory": "/dst",
            "max_concurrent_copies": 4,
        })
        assert results["source_directory"] is True
        assert results["destination_directory"] is True
        assert results["max_concurrent_copies"] is True
        assert service.get("source_directory") == "/src"
        assert service.get("max_concurrent_copies") == 4


class TestGetAllWithMetadata:

    async def test_returns_all_settings_with_metadata(self, service):
        result = service.get_all_with_metadata()
        assert len(result) == len(USER_SETTINGS_SCHEMA)
        keys = {s["key"] for s in result}
        assert "source_directory" in keys
        assert "max_concurrent_copies" in keys

        for s in result:
            assert "key" in s
            assert "value" in s
            assert "type" in s
            assert "default" in s
            assert "requires_restart" in s

    async def test_requires_restart_metadata(self, service):
        result = service.get_all_with_metadata()
        by_key = {s["key"]: s for s in result}
        assert by_key["source_directory"]["requires_restart"] is True
        assert by_key["output_folder_rules"]["requires_restart"] is False


class TestEnvMigration:

    async def test_migrates_env_values_to_db(self, db):
        """When DB has default and env has different value, env wins."""
        lock = asyncio.Lock()
        svc = UserSettingsService(db=db, write_lock=lock)

        mock_settings = MagicMock()
        mock_settings.source_directory = "/from/env"
        mock_settings.destination_directory = "/dest/env"
        mock_settings.network_share_url = ""
        mock_settings.enable_auto_mount = False
        mock_settings.macos_mount_point = ""
        mock_settings.tally_light_switch_ip = "10.0.0.1"
        mock_settings.output_folder_template_enabled = False
        mock_settings.output_folder_rules = ""
        mock_settings.output_folder_default_category = "OTHER"
        mock_settings.output_folder_date_format = "filename[0:6]"
        mock_settings.max_concurrent_copies = 7
        mock_settings.justin_auto_stop_minutes = 0

        await svc.init(env_settings=mock_settings)

        assert svc.get("source_directory") == "/from/env"
        assert svc.get("destination_directory") == "/dest/env"
        assert svc.get("tally_light_switch_ip") == "10.0.0.1"
        # These stayed at default (env == default)
        assert svc.get("enable_auto_mount") is False
        assert svc.get("max_concurrent_copies") == 7

    async def test_does_not_overwrite_existing_db_values(self, db):
        """If DB already has a non-default value, env does NOT overwrite."""
        await db.execute(
            "INSERT INTO user_settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("source_directory", "/already/set", "2026-04-08T00:00:00+00:00"),
        )
        lock = asyncio.Lock()
        svc = UserSettingsService(db=db, write_lock=lock)

        mock_settings = MagicMock()
        mock_settings.source_directory = "/from/env"
        mock_settings.destination_directory = ""
        mock_settings.network_share_url = ""
        mock_settings.enable_auto_mount = False
        mock_settings.macos_mount_point = ""
        mock_settings.tally_light_switch_ip = ""
        mock_settings.output_folder_template_enabled = False
        mock_settings.output_folder_rules = ""
        mock_settings.output_folder_default_category = "OTHER"
        mock_settings.output_folder_date_format = "filename[0:6]"
        mock_settings.max_concurrent_copies = 7
        mock_settings.justin_auto_stop_minutes = 0

        await svc.init(env_settings=mock_settings)

        # DB value is preserved — it's not the default
        assert svc.get("source_directory") == "/already/set"


class TestRequiresRestart:

    def test_restart_settings_defined(self):
        assert "source_directory" in REQUIRES_RESTART
        assert "destination_directory" in REQUIRES_RESTART
        assert "max_concurrent_copies" in REQUIRES_RESTART
        assert "output_folder_rules" not in REQUIRES_RESTART
        assert "justin_auto_stop_minutes" not in REQUIRES_RESTART
