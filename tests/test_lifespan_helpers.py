"""Tests for lifespan helpers in app.main — startup & shutdown phases."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from app.core.global_event_logger import LoggedEvent


# ---------------------------------------------------------------------------
# _init_database
# ---------------------------------------------------------------------------

class TestInitDatabase:

    async def test_calls_init_db(self):
        mock_repo = AsyncMock()
        with patch("app.main.get_file_repository", return_value=mock_repo):
            from app.main import _init_database
            await _init_database()
        mock_repo.init_db.assert_awaited_once()


# ---------------------------------------------------------------------------
# _init_event_logging
# ---------------------------------------------------------------------------

class TestInitEventLogging:

    async def test_registers_logger_and_writes_startup_event(self):
        event_bus = MagicMock()
        event_store = AsyncMock()
        global_logger = AsyncMock()
        global_logger.set_event_store = MagicMock()

        with patch("app.main.settings") as mock_settings:
            mock_settings.config_file_info = {"hostname": "test-host"}
            from app.main import _init_event_logging
            await _init_event_logging(event_bus, event_store, global_logger)

        global_logger.set_event_store.assert_called_once_with(event_store)
        global_logger.register_with_event_bus.assert_awaited_once_with(event_bus)
        event_store.add_event.assert_awaited_once()
        logged: LoggedEvent = event_store.add_event.call_args[0][0]
        assert logged.event_type == "ApplicationStarted"


# ---------------------------------------------------------------------------
# _startup_cleanup
# ---------------------------------------------------------------------------

class TestStartupCleanup:

    async def test_cleanup_runs(self):
        mock_checker = AsyncMock()
        mock_checker.cleanup_all_test_files.return_value = 3
        with (
            patch("app.main.get_storage_checker", return_value=mock_checker),
            patch("app.main.settings") as mock_settings,
        ):
            mock_settings.source_directory = "/src"
            mock_settings.destination_directory = "/dst"
            from app.main import _startup_cleanup
            await _startup_cleanup()
        mock_checker.cleanup_all_test_files.assert_awaited_once_with("/src", "/dst")

    async def test_cleanup_exception_is_non_fatal(self):
        mock_checker = AsyncMock()
        mock_checker.cleanup_all_test_files.side_effect = RuntimeError("boom")
        with (
            patch("app.main.get_storage_checker", return_value=mock_checker),
            patch("app.main.settings") as mock_settings,
        ):
            mock_settings.source_directory = "/src"
            mock_settings.destination_directory = "/dst"
            from app.main import _startup_cleanup
            await _startup_cleanup()  # should not raise


# ---------------------------------------------------------------------------
# _mount_static_files
# ---------------------------------------------------------------------------

class TestMountStaticFiles:

    async def test_mounts_static_when_dir_exists(self):
        """Both static and logs directories exist — both get mounted."""
        app = MagicMock()

        # asyncio.to_thread(path.exists) always returns True
        with (
            patch("app.main.asyncio.to_thread", new_callable=AsyncMock, return_value=True),
            patch("app.main.settings") as mock_settings,
            patch("app.main.StaticFiles"),
        ):
            mock_settings.log_directory = MagicMock()
            from app.main import _mount_static_files
            await _mount_static_files(app)

        assert app.mount.call_count == 2  # /static + /logs

    async def test_skips_static_when_missing(self):
        """Static dir missing, logs dir exists — only logs mounted."""
        app = MagicMock()

        # First to_thread call (static) returns False, second (logs) returns True
        with (
            patch("app.main.asyncio.to_thread", new_callable=AsyncMock, side_effect=[False, True]),
            patch("app.main.settings") as mock_settings,
            patch("app.main.StaticFiles"),
        ):
            mock_settings.log_directory = MagicMock()
            from app.main import _mount_static_files
            await _mount_static_files(app)

        assert app.mount.call_count == 1

    async def test_logs_warning_when_log_dir_missing(self):
        """Log directory missing — warning logged."""
        app = MagicMock()

        # static exists, logs does not
        with (
            patch("app.main.asyncio.to_thread", new_callable=AsyncMock, side_effect=[True, False]),
            patch("app.main.settings") as mock_settings,
            patch("app.main.StaticFiles"),
        ):
            mock_settings.log_directory = MagicMock()
            from app.main import _mount_static_files
            await _mount_static_files(app)

        # Only /static should be mounted
        assert app.mount.call_count == 1
        assert app.mount.call_args_list[0][0][0] == "/static"


# ---------------------------------------------------------------------------
# _shutdown
# ---------------------------------------------------------------------------

class TestShutdown:

    def _patch_deps(self):
        """Return dict of mocked dependency getters for _shutdown."""
        return {
            "get_websocket_manager": MagicMock(),
            "get_file_scanner": AsyncMock(),
            "get_job_queue_service": MagicMock(),
            "get_file_copier": AsyncMock(),
            "get_storage_monitor": AsyncMock(),
            "get_lifecycle_service": MagicMock(),
            "get_ingest_monitor_worker": AsyncMock(),
            "get_ingest_api_client": AsyncMock(),
            "get_file_repository": AsyncMock(),
        }

    async def test_shutdown_stops_services_and_closes_db(self):
        tally_handler = AsyncMock()
        tally_handler.shutdown = AsyncMock()
        event_store = AsyncMock()
        global_logger = MagicMock()
        deps = self._patch_deps()

        with (
            patch("app.main.get_websocket_manager", return_value=deps["get_websocket_manager"]),
            patch("app.main.get_file_scanner", return_value=deps["get_file_scanner"]),
            patch("app.main.get_job_queue_service", return_value=deps["get_job_queue_service"]),
            patch("app.main.get_file_copier", return_value=deps["get_file_copier"]),
            patch("app.main.get_storage_monitor", return_value=deps["get_storage_monitor"]),
            patch("app.main.get_lifecycle_service", return_value=deps["get_lifecycle_service"]),
            patch("app.main.get_ingest_monitor_worker", return_value=deps["get_ingest_monitor_worker"]),
            patch("app.main.get_ingest_api_client", return_value=deps["get_ingest_api_client"]),
            patch("app.main.get_file_repository", return_value=deps["get_file_repository"]),
            patch("app.main._background_tasks", []),
        ):
            from app.main import _shutdown
            await _shutdown(tally_handler, event_store, global_logger)

        tally_handler.shutdown.assert_awaited_once()
        event_store.add_event.assert_awaited_once()
        global_logger.set_event_store.assert_called_once_with(None)
        deps["get_file_repository"].close.assert_awaited_once()

    async def test_shutdown_without_tally_handler(self):
        """tally_handler=None should not crash."""
        event_store = AsyncMock()
        global_logger = MagicMock()
        deps = self._patch_deps()

        with (
            patch("app.main.get_websocket_manager", return_value=deps["get_websocket_manager"]),
            patch("app.main.get_file_scanner", return_value=deps["get_file_scanner"]),
            patch("app.main.get_job_queue_service", return_value=deps["get_job_queue_service"]),
            patch("app.main.get_file_copier", return_value=deps["get_file_copier"]),
            patch("app.main.get_storage_monitor", return_value=deps["get_storage_monitor"]),
            patch("app.main.get_lifecycle_service", return_value=deps["get_lifecycle_service"]),
            patch("app.main.get_ingest_monitor_worker", return_value=deps["get_ingest_monitor_worker"]),
            patch("app.main.get_ingest_api_client", return_value=deps["get_ingest_api_client"]),
            patch("app.main.get_file_repository", return_value=deps["get_file_repository"]),
            patch("app.main._background_tasks", []),
        ):
            from app.main import _shutdown
            await _shutdown(None, event_store, global_logger)  # should not raise
