"""Tests for StorageMonitorService."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.storage.storage_monitor.storage_monitor import StorageMonitorService
from app.models import StorageInfo, StorageStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(**overrides):
    s = MagicMock()
    s.source_directory = overrides.get("source_directory", "/source")
    s.destination_directory = overrides.get("destination_directory", "/dest")
    s.source_warning_threshold_gb = overrides.get("source_warning_threshold_gb", 10.0)
    s.source_critical_threshold_gb = overrides.get("source_critical_threshold_gb", 5.0)
    s.destination_warning_threshold_gb = overrides.get("destination_warning_threshold_gb", 50.0)
    s.destination_critical_threshold_gb = overrides.get("destination_critical_threshold_gb", 20.0)
    s.storage_check_interval_seconds = overrides.get("storage_check_interval_seconds", 30)
    s.storage_check_timeout_seconds = overrides.get("storage_check_timeout_seconds", 30.0)
    return s


def _make_storage_info(
    path="/dest",
    accessible=True,
    status=StorageStatus.OK,
    free=100.0,
    total=500.0,
    error_message=None,
):
    return StorageInfo(
        path=path,
        is_accessible=accessible,
        has_write_access=accessible,
        free_space_gb=free,
        total_space_gb=total,
        used_space_gb=total - free,
        status=status,
        warning_threshold_gb=50.0,
        critical_threshold_gb=20.0,
        last_checked=datetime.now(),
        error_message=error_message,
    )


def _build_service(settings=None, checker=None, event_bus=None, mount_service=None):
    settings = settings or _make_settings()
    checker = checker or AsyncMock()
    event_bus = event_bus or AsyncMock()
    svc = StorageMonitorService(
        settings=settings,
        storage_checker=checker,
        event_bus=event_bus,
        network_mount_service=mount_service,
    )
    return svc, settings, checker, event_bus


# ---------------------------------------------------------------------------
# Lifecycle: start / stop
# ---------------------------------------------------------------------------

class TestLifecycle:
    async def test_start_sets_running(self):
        svc, settings, checker, _ = _build_service()
        checker.check_path = AsyncMock(return_value=_make_storage_info(path="/source"))

        await svc.start_monitoring()
        assert svc._is_running is True
        assert svc._monitor_task is not None
        await svc.stop_monitoring()

    async def test_start_twice_is_noop(self):
        svc, _, checker, _ = _build_service()
        checker.check_path = AsyncMock(return_value=_make_storage_info())
        await svc.start_monitoring()
        task = svc._monitor_task
        await svc.start_monitoring()  # second call
        assert svc._monitor_task is task  # same task, not replaced
        await svc.stop_monitoring()

    async def test_stop_cancels_task(self):
        svc, _, checker, _ = _build_service()
        checker.check_path = AsyncMock(return_value=_make_storage_info())
        await svc.start_monitoring()
        assert svc._is_running
        await svc.stop_monitoring()
        assert svc._is_running is False

    async def test_stop_when_not_running(self):
        svc, *_ = _build_service()
        # Should not raise
        await svc.stop_monitoring()


# ---------------------------------------------------------------------------
# _check_single_storage basics
# ---------------------------------------------------------------------------

class TestCheckSingleStorage:
    async def test_accessible_destination_updates_state(self):
        svc, settings, checker, _ = _build_service()
        ok_info = _make_storage_info(path="/dest", accessible=True, status=StorageStatus.OK)
        checker.check_path = AsyncMock(return_value=ok_info)

        await svc._check_single_storage(
            storage_type="destination",
            path="/dest",
            warning_threshold=50.0,
            critical_threshold=20.0,
        )

        assert svc.get_destination_info() == ok_info

    async def test_source_updates_source_state(self):
        svc, settings, checker, _ = _build_service()
        ok_info = _make_storage_info(path="/source", status=StorageStatus.OK)
        checker.check_path = AsyncMock(return_value=ok_info)

        await svc._check_single_storage(
            storage_type="source",
            path="/source",
            warning_threshold=10.0,
            critical_threshold=5.0,
        )

        assert svc.get_source_info() == ok_info

    async def test_timeout_creates_error_info(self):
        """If storage_checker.check_path times out, synthetic ERROR info is created."""
        svc, settings, checker, _ = _build_service()

        async def slow_check(**kwargs):
            await asyncio.sleep(10)

        checker.check_path = slow_check

        with patch.object(
            svc._directory_manager, "ensure_directory_exists", new_callable=AsyncMock, return_value=False
        ):
            await svc._check_single_storage(
                storage_type="destination",
                path="/dest",
                warning_threshold=50.0,
                critical_threshold=20.0,
                immediate_timeout=0.05,  # very short timeout
            )

        info = svc.get_destination_info()
        assert info is not None
        assert info.status == StorageStatus.ERROR
        assert info.is_accessible is False

    async def test_exception_does_not_propagate(self):
        """Errors inside _check_single_storage are caught and logged."""
        svc, _, checker, _ = _build_service()
        checker.check_path = AsyncMock(side_effect=RuntimeError("disk gone"))

        # Should not raise
        await svc._check_single_storage(
            storage_type="source",
            path="/source",
            warning_threshold=10.0,
            critical_threshold=5.0,
        )


# ---------------------------------------------------------------------------
# Inaccessible destination → directory recreation
# ---------------------------------------------------------------------------

class TestDirectoryRecreation:
    async def test_inaccessible_triggers_recreation(self):
        svc, _, checker, _ = _build_service()

        bad_info = _make_storage_info(path="/dest", accessible=False, status=StorageStatus.ERROR)
        ok_info = _make_storage_info(path="/dest", accessible=True, status=StorageStatus.OK)

        # First call returns inaccessible; after recreation, second call returns OK
        checker.check_path = AsyncMock(side_effect=[bad_info, ok_info])

        with patch.object(
            svc._directory_manager, "ensure_directory_exists", new_callable=AsyncMock, return_value=True
        ) as mock_recreate:
            await svc._check_single_storage(
                storage_type="destination",
                path="/dest",
                warning_threshold=50.0,
                critical_threshold=20.0,
            )
            mock_recreate.assert_awaited_once_with("/dest", "destination")

        # After recreation + re-check the state should be OK
        assert svc.get_destination_info().status == StorageStatus.OK

    async def test_recreation_failure_keeps_error(self):
        svc, _, checker, _ = _build_service()
        bad_info = _make_storage_info(path="/dest", accessible=False, status=StorageStatus.ERROR)
        checker.check_path = AsyncMock(return_value=bad_info)

        with patch.object(
            svc._directory_manager, "ensure_directory_exists", new_callable=AsyncMock, return_value=False
        ):
            await svc._check_single_storage(
                storage_type="destination",
                path="/dest",
                warning_threshold=50.0,
                critical_threshold=20.0,
            )

        assert svc.get_destination_info().status == StorageStatus.ERROR


# ---------------------------------------------------------------------------
# Network mount flow
# ---------------------------------------------------------------------------

class TestNetworkMountFlow:
    def _mount_service(self, configured=True, share_url="//server/share", mount_result=True):
        ms = MagicMock()
        ms.is_network_mount_configured.return_value = configured
        ms.get_network_share_url.return_value = share_url
        ms.ensure_mount_available = AsyncMock(return_value=mount_result)
        return ms

    async def test_mount_attempted_when_configured(self):
        mount_svc = self._mount_service(mount_result=True)
        svc, _, checker, _ = _build_service(mount_service=mount_svc)

        bad_info = _make_storage_info(path="/dest", accessible=False, status=StorageStatus.ERROR)
        ok_info = _make_storage_info(path="/dest", accessible=True, status=StorageStatus.OK)
        checker.check_path = AsyncMock(side_effect=[bad_info, ok_info])

        await svc._check_single_storage(
            storage_type="destination",
            path="/dest",
            warning_threshold=50.0,
            critical_threshold=20.0,
        )

        mount_svc.ensure_mount_available.assert_awaited_once()
        assert svc.get_destination_info().status == StorageStatus.OK

    async def test_mount_failure_keeps_error(self):
        mount_svc = self._mount_service(mount_result=False)
        svc, _, checker, _ = _build_service(mount_service=mount_svc)

        bad_info = _make_storage_info(path="/dest", accessible=False, status=StorageStatus.ERROR)
        checker.check_path = AsyncMock(return_value=bad_info)

        await svc._check_single_storage(
            storage_type="destination",
            path="/dest",
            warning_threshold=50.0,
            critical_threshold=20.0,
        )

        assert svc.get_destination_info().status == StorageStatus.ERROR

    async def test_mount_not_attempted_for_source(self):
        mount_svc = self._mount_service()
        svc, _, checker, _ = _build_service(mount_service=mount_svc)

        bad_info = _make_storage_info(path="/source", accessible=False, status=StorageStatus.ERROR)
        checker.check_path = AsyncMock(return_value=bad_info)

        with patch.object(
            svc._directory_manager, "ensure_directory_exists", new_callable=AsyncMock, return_value=False
        ):
            await svc._check_single_storage(
                storage_type="source",
                path="/source",
                warning_threshold=10.0,
                critical_threshold=5.0,
            )

        mount_svc.ensure_mount_available.assert_not_awaited()

    async def test_parallel_mount_prevented(self):
        """Second mount call while one is in progress should be skipped."""
        mount_svc = self._mount_service(mount_result=True)
        svc, _, checker, _ = _build_service(mount_service=mount_svc)

        bad_info = _make_storage_info(path="/dest", accessible=False, status=StorageStatus.ERROR)
        checker.check_path = AsyncMock(return_value=bad_info)

        # Simulate mount already in progress
        svc._mount_in_progress = True

        await svc._check_single_storage(
            storage_type="destination",
            path="/dest",
            warning_threshold=50.0,
            critical_threshold=20.0,
        )

        # Mount should not have been attempted
        mount_svc.ensure_mount_available.assert_not_awaited()
        # State should not have been updated (returned early)
        assert svc.get_destination_info() is None


# ---------------------------------------------------------------------------
# Destination recovery & unavailable detection
# ---------------------------------------------------------------------------

class TestRecoveryAndUnavailableDetection:
    async def test_destination_recovery_detected(self):
        svc, _, checker, _ = _build_service()

        # First set destination to ERROR
        err_info = _make_storage_info(path="/dest", accessible=False, status=StorageStatus.ERROR)
        svc._storage_state.update_destination_info(err_info)

        # Now check returns OK
        ok_info = _make_storage_info(path="/dest", accessible=True, status=StorageStatus.OK)
        checker.check_path = AsyncMock(return_value=ok_info)

        with patch.object(
            svc._notification_handler, "publish_destination_recovered", new_callable=AsyncMock
        ) as mock_recovered:
            await svc._check_single_storage(
                storage_type="destination",
                path="/dest",
                warning_threshold=50.0,
                critical_threshold=20.0,
            )
            mock_recovered.assert_awaited_once()

    async def test_destination_unavailable_detected(self):
        svc, _, checker, _ = _build_service()

        # First set destination to OK
        ok_info = _make_storage_info(path="/dest", accessible=True, status=StorageStatus.OK)
        svc._storage_state.update_destination_info(ok_info)

        # Now check returns ERROR
        err_info = _make_storage_info(path="/dest", accessible=False, status=StorageStatus.ERROR)
        checker.check_path = AsyncMock(return_value=err_info)

        with patch.object(
            svc._directory_manager, "ensure_directory_exists", new_callable=AsyncMock, return_value=False
        ):
            with patch.object(
                svc._notification_handler, "publish_destination_unavailable", new_callable=AsyncMock
            ) as mock_unavail:
                await svc._check_single_storage(
                    storage_type="destination",
                    path="/dest",
                    warning_threshold=50.0,
                    critical_threshold=20.0,
                )
                mock_unavail.assert_awaited_once()

    async def test_source_never_triggers_recovery(self):
        svc, _, checker, _ = _build_service()

        err_info = _make_storage_info(path="/source", accessible=False, status=StorageStatus.ERROR)
        svc._storage_state.update_source_info(err_info)

        ok_info = _make_storage_info(path="/source", accessible=True, status=StorageStatus.OK)
        checker.check_path = AsyncMock(return_value=ok_info)

        with patch.object(
            svc._notification_handler, "publish_destination_recovered", new_callable=AsyncMock
        ) as mock_recovered:
            await svc._check_single_storage(
                storage_type="source",
                path="/source",
                warning_threshold=10.0,
                critical_threshold=5.0,
            )
            mock_recovered.assert_not_awaited()

    async def test_warning_to_critical_detected_as_unavailable(self):
        """WARNING → CRITICAL should trigger destination unavailable."""
        svc, _, checker, _ = _build_service()

        warn_info = _make_storage_info(path="/dest", accessible=True, status=StorageStatus.WARNING, free=30.0)
        svc._storage_state.update_destination_info(warn_info)

        crit_info = _make_storage_info(path="/dest", accessible=True, status=StorageStatus.CRITICAL, free=5.0)
        checker.check_path = AsyncMock(return_value=crit_info)

        with patch.object(
            svc._notification_handler, "publish_destination_unavailable", new_callable=AsyncMock
        ) as mock_unavail:
            await svc._check_single_storage(
                storage_type="destination",
                path="/dest",
                warning_threshold=50.0,
                critical_threshold=20.0,
            )
            mock_unavail.assert_awaited_once()

    async def test_critical_to_warning_triggers_recovery(self):
        """CRITICAL → WARNING should trigger destination recovered."""
        svc, _, checker, _ = _build_service()

        crit_info = _make_storage_info(path="/dest", accessible=True, status=StorageStatus.CRITICAL, free=5.0)
        svc._storage_state.update_destination_info(crit_info)

        warn_info = _make_storage_info(path="/dest", accessible=True, status=StorageStatus.WARNING, free=30.0)
        checker.check_path = AsyncMock(return_value=warn_info)

        with patch.object(
            svc._notification_handler, "publish_destination_recovered", new_callable=AsyncMock
        ) as mock_recovered:
            await svc._check_single_storage(
                storage_type="destination",
                path="/dest",
                warning_threshold=50.0,
                critical_threshold=20.0,
            )
            mock_recovered.assert_awaited_once()

    async def test_ok_to_warning_not_detected_as_unavailable(self):
        """OK → WARNING should NOT trigger destination unavailable."""
        svc, _, checker, _ = _build_service()

        ok_info = _make_storage_info(path="/dest", accessible=True, status=StorageStatus.OK)
        svc._storage_state.update_destination_info(ok_info)

        warn_info = _make_storage_info(path="/dest", accessible=True, status=StorageStatus.WARNING, free=30.0)
        checker.check_path = AsyncMock(return_value=warn_info)

        with patch.object(
            svc._notification_handler, "publish_destination_unavailable", new_callable=AsyncMock
        ) as mock_unavail:
            await svc._check_single_storage(
                storage_type="destination",
                path="/dest",
                warning_threshold=50.0,
                critical_threshold=20.0,
            )
            mock_unavail.assert_not_awaited()


# ---------------------------------------------------------------------------
# handle_network_failure_detected
# ---------------------------------------------------------------------------

class TestNetworkFailureDetected:
    async def test_triggers_immediate_destination_check(self):
        svc, settings, checker, _ = _build_service()
        ok_info = _make_storage_info(path="/dest", accessible=True, status=StorageStatus.OK)
        checker.check_path = AsyncMock(return_value=ok_info)

        event = MagicMock()
        event.error_message = "Connection reset"

        await svc.handle_network_failure_detected(event)

        # check_path should have been called (immediate check)
        checker.check_path.assert_awaited()

    async def test_not_configured_only_broadcast_when_mount_not_configured(self):
        """NOT_CONFIGURED should NOT be broadcast when mount IS configured but destination has issues."""
        mount_svc = MagicMock()
        mount_svc.is_network_mount_configured.return_value = True

        svc, _, checker, _ = _build_service(mount_service=mount_svc)

        # Destination returns CRITICAL (e.g., read-only)
        crit_info = _make_storage_info(path="/dest", accessible=True, status=StorageStatus.CRITICAL, free=5.0)
        checker.check_path = AsyncMock(return_value=crit_info)

        event = MagicMock()
        event.error_message = "Connection reset"

        with patch.object(
            svc._mount_broadcaster, "broadcast_not_configured", new_callable=AsyncMock
        ) as mock_not_configured:
            await svc.handle_network_failure_detected(event)
            mock_not_configured.assert_not_awaited()

    async def test_not_configured_broadcast_when_mount_not_configured(self):
        """NOT_CONFIGURED SHOULD be broadcast when mount is not configured."""
        svc, _, checker, _ = _build_service()  # no mount_service

        err_info = _make_storage_info(path="/dest", accessible=False, status=StorageStatus.ERROR)
        checker.check_path = AsyncMock(return_value=err_info)

        event = MagicMock()
        event.error_message = "Connection reset"

        with patch.object(
            svc._directory_manager, "ensure_directory_exists", new_callable=AsyncMock, return_value=False
        ):
            with patch.object(
                svc._mount_broadcaster, "broadcast_not_configured", new_callable=AsyncMock
            ) as mock_not_configured:
                await svc.handle_network_failure_detected(event)
                mock_not_configured.assert_awaited()


# ---------------------------------------------------------------------------
# trigger_immediate_check
# ---------------------------------------------------------------------------

class TestTriggerImmediateCheck:
    async def test_destination_check(self):
        svc, _, checker, _ = _build_service()
        svc._is_running = True
        ok_info = _make_storage_info(path="/dest")
        checker.check_path = AsyncMock(return_value=ok_info)

        await svc.trigger_immediate_check("destination")
        checker.check_path.assert_awaited()

    async def test_source_check(self):
        svc, _, checker, _ = _build_service()
        svc._is_running = True
        ok_info = _make_storage_info(path="/source")
        checker.check_path = AsyncMock(return_value=ok_info)

        await svc.trigger_immediate_check("source")
        checker.check_path.assert_awaited()

    async def test_not_running_skips(self):
        svc, _, checker, _ = _build_service()
        svc._is_running = False
        checker.check_path = AsyncMock()

        await svc.trigger_immediate_check("destination")
        checker.check_path.assert_not_awaited()


# ---------------------------------------------------------------------------
# State accessors
# ---------------------------------------------------------------------------

class TestStateAccessors:
    def test_overall_status_default_ok(self):
        svc, *_ = _build_service()
        assert svc.get_overall_status() == StorageStatus.OK

    def test_directory_readiness_defaults(self):
        svc, *_ = _build_service()
        readiness = svc.get_directory_readiness()
        assert readiness["source_ready"] is False
        assert readiness["destination_ready"] is False

    def test_monitoring_status_includes_running(self):
        svc, *_ = _build_service()
        status = svc.get_monitoring_status()
        assert "is_running" in status
        assert status["is_running"] is False

    def test_is_destination_available_false_when_no_info(self):
        svc, *_ = _build_service()
        assert svc.is_destination_available() is False

    def test_is_destination_available_true_when_ok(self):
        svc, *_ = _build_service()
        ok_info = _make_storage_info(status=StorageStatus.OK)
        svc._storage_state.update_destination_info(ok_info)
        assert svc.is_destination_available() is True

    def test_is_destination_available_false_when_error(self):
        svc, *_ = _build_service()
        err_info = _make_storage_info(status=StorageStatus.ERROR, accessible=False)
        svc._storage_state.update_destination_info(err_info)
        assert svc.is_destination_available() is False

    async def test_subscribe_to_events(self):
        svc, _, _, event_bus = _build_service()
        await svc.subscribe_to_events()
        event_bus.subscribe.assert_awaited()
