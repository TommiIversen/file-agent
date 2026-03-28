"""Tests for PresentationEventHandlers — event → JSON → broadcast."""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from app.domains.presentation.event_handlers import PresentationEventHandlers, _serialize_storage_info, _serialize_tracked_file
from app.core.events.file_events import (
    FileDiscoveredEvent,
    FileStatusChangedEvent,
    FileCopyProgressEvent,
    FileCopyCompletedEvent,
)
from app.core.events.scanner_events import ScannerStatusChangedEvent
from app.core.events.storage_events import StorageStatusChangedEvent, MountStatusChangedEvent
from app.domains.ingest_monitor.events import (
    IngestStatusUpdatedEvent,
    ChannelErrorDetectedEvent,
    IngestOnlineEvent,
    IngestOfflineEvent,
    RecordingPathsDiscoveredEvent,
    AutoStopWarningEvent,
    AutoStopTriggeredEvent,
)
from app.domains.tally_light.monitor_service import (
    TallySwitchStatusUpdatedEvent,
    TallySwitchOnlineEvent,
    TallySwitchOfflineEvent,
    TallySwitchStatus,
)
from app.models import FileStatus, StorageStatus, MountStatus, StorageInfo, StorageUpdate, MountStatusUpdate, TrackedFile


@pytest.fixture
def ws_manager():
    return MagicMock()


@pytest.fixture
def file_repo():
    return AsyncMock()


@pytest.fixture
def handler(ws_manager, file_repo):
    return PresentationEventHandlers(websocket_manager=ws_manager, file_repository=file_repo)


def _make_storage_info(**overrides):
    defaults = dict(
        path="/dest",
        is_accessible=True,
        has_write_access=True,
        free_space_gb=100.0,
        total_space_gb=500.0,
        used_space_gb=400.0,
        status=StorageStatus.OK,
        warning_threshold_gb=50.0,
        critical_threshold_gb=10.0,
        last_checked=datetime(2026, 1, 1, 12, 0, 0),
        error_message=None,
    )
    defaults.update(overrides)
    return StorageInfo(**defaults)


def _make_tally_status(**overrides):
    defaults = dict(
        is_online=True,
        switch_type="mock",
        ip_address="192.168.1.100",
        last_checked=datetime(2026, 1, 1, 12, 0, 0),
        error_message=None,
    )
    defaults.update(overrides)
    return TallySwitchStatus(**defaults)


# ── Utility tests ──────────────────────────────────────────────

class TestSerializeStorageInfo:
    def test_none_returns_none(self):
        assert _serialize_storage_info(None) is None

    def test_serializes_all_fields(self):
        info = _make_storage_info()
        result = _serialize_storage_info(info)
        assert result["path"] == "/dest"
        assert result["is_accessible"] is True
        assert result["status"] == "OK"
        assert result["free_space_gb"] == 100.0
        assert result["last_checked"] == "2026-01-01T12:00:00"


class TestSerializeTrackedFile:
    def test_includes_file_size_mb(self):
        tf = TrackedFile(file_path="/src/test.mxf", file_size=10 * 1024 * 1024)
        result = _serialize_tracked_file(tf)
        assert result["file_size_mb"] == 10.0
        assert result["file_path"] == "/src/test.mxf"


# ── Handler tests ──────────────────────────────────────────────

class TestFileDiscoveredEvent:
    @pytest.mark.asyncio
    async def test_broadcasts_file_discovered(self, handler, ws_manager):
        event = FileDiscoveredEvent(
            file_path="/src/test.mxf",
            file_size=5_000_000,
            last_write_time=1700000000.0,
        )
        await handler.handle_file_discovered_event(event)

        ws_manager.broadcast_message.assert_called_once()
        msg = ws_manager.broadcast_message.call_args[0][0]
        assert msg["type"] == "file_discovered"
        assert msg["data"]["file_path"] == "/src/test.mxf"
        assert msg["data"]["file_size"] == 5_000_000
        assert msg["data"]["status"] == FileStatus.DISCOVERED.value


class TestFileStatusChangedEvent:
    @pytest.mark.asyncio
    async def test_broadcasts_status_change(self, handler, ws_manager, file_repo):
        tf = TrackedFile(id="f1", file_path="/src/f.mxf", file_size=1024)
        file_repo.get_by_id.return_value = tf

        event = FileStatusChangedEvent(
            file_id="f1",
            file_path="/src/f.mxf",
            old_status=FileStatus.DISCOVERED,
            new_status=FileStatus.READY,
        )
        await handler.handle_file_status_changed_event(event)

        ws_manager.broadcast_message.assert_called_once()
        msg = ws_manager.broadcast_message.call_args[0][0]
        assert msg["type"] == "file_update"
        assert msg["data"]["new_status"] == "Ready"
        assert msg["data"]["old_status"] == "Discovered"

    @pytest.mark.asyncio
    async def test_skips_unknown_file(self, handler, ws_manager, file_repo):
        file_repo.get_by_id.return_value = None

        event = FileStatusChangedEvent(
            file_id="unknown",
            file_path="/src/no.mxf",
            old_status=None,
            new_status=FileStatus.FAILED,
        )
        await handler.handle_file_status_changed_event(event)

        ws_manager.broadcast_message.assert_not_called()


class TestFileCopyProgress:
    @pytest.mark.asyncio
    async def test_broadcasts_progress(self, handler, ws_manager):
        event = FileCopyProgressEvent(
            file_id="f1",
            bytes_copied=500,
            total_bytes=1000,
            copy_speed_mbps=12.345,
        )
        await handler.handle_file_copy_progress(event)

        msg = ws_manager.broadcast_message.call_args[0][0]
        assert msg["type"] == "file_progress_update"
        assert msg["data"]["progress_percent"] == 50.0
        assert msg["data"]["copy_speed_mbps"] == 12.35

    @pytest.mark.asyncio
    async def test_zero_total_bytes_gives_zero_percent(self, handler, ws_manager):
        event = FileCopyProgressEvent(
            file_id="f1", bytes_copied=0, total_bytes=0, copy_speed_mbps=0.0
        )
        await handler.handle_file_copy_progress(event)

        msg = ws_manager.broadcast_message.call_args[0][0]
        assert msg["data"]["progress_percent"] == 0.0


class TestFileCopyCompleted:
    @pytest.mark.asyncio
    async def test_broadcasts_final_progress_and_completion(self, handler, ws_manager):
        event = FileCopyCompletedEvent(
            file_id="f1",
            file_path="/src/f.mxf",
            destination_path="/dest/f.mxf",
            bytes_copied=1000,
            source_size=1000,
            dest_size=1000,
        )
        await handler.handle_file_copy_completed(event)

        assert ws_manager.broadcast_message.call_count == 2
        progress_msg = ws_manager.broadcast_message.call_args_list[0][0][0]
        assert progress_msg["type"] == "file_progress_update"
        assert progress_msg["data"]["progress_percent"] == 100.0
        assert progress_msg["data"]["is_final"] is True

        completion_msg = ws_manager.broadcast_message.call_args_list[1][0][0]
        assert completion_msg["type"] == "file_copy_completed"
        assert completion_msg["data"]["destination_path"] == "/dest/f.mxf"

    @pytest.mark.asyncio
    async def test_growing_file_flag(self, handler, ws_manager):
        event = FileCopyCompletedEvent(
            file_id="f1",
            file_path="/src/f.mxf",
            destination_path="/dest/f.mxf",
            bytes_copied=2000,
            source_size=1500,
            dest_size=2000,
        )
        await handler.handle_file_copy_completed(event)

        completion_msg = ws_manager.broadcast_message.call_args_list[1][0][0]
        assert completion_msg["data"]["is_growing_file"] is True


class TestScannerStatusEvent:
    @pytest.mark.asyncio
    async def test_broadcasts_scanner_status(self, handler, ws_manager):
        event = ScannerStatusChangedEvent(is_scanning=True, is_paused=False)
        await handler.handle_scanner_status_event(event)

        msg = ws_manager.broadcast_message.call_args[0][0]
        assert msg["type"] == "scanner_status"
        assert msg["data"]["scanning"] is True
        assert msg["data"]["paused"] is False

    @pytest.mark.asyncio
    async def test_updates_internal_state(self, handler):
        event = ScannerStatusChangedEvent(is_scanning=False, is_paused=True)
        await handler.handle_scanner_status_event(event)

        assert handler._scanner_status == {"scanning": False, "paused": True}


class TestStorageStatusEvent:
    @pytest.mark.asyncio
    async def test_broadcasts_storage_update(self, handler, ws_manager):
        info = _make_storage_info()
        update = StorageUpdate(
            storage_type="destination",
            old_status=StorageStatus.OK,
            new_status=StorageStatus.WARNING,
            storage_info=info,
        )
        event = StorageStatusChangedEvent(update=update)
        await handler.handle_storage_status_event(event)

        msg = ws_manager.broadcast_message.call_args[0][0]
        assert msg["type"] == "storage_update"
        assert msg["data"]["storage_type"] == "destination"
        assert msg["data"]["new_status"] == "WARNING"
        assert msg["data"]["storage_info"]["path"] == "/dest"


class TestMountStatusEvent:
    @pytest.mark.asyncio
    async def test_broadcasts_mount_status(self, handler, ws_manager):
        update = MountStatusUpdate(
            storage_type="destination",
            mount_status=MountStatus.SUCCESS,
            share_url="//nas/share",
            mount_path="/mnt/share",
            target_path="/dest",
        )
        event = MountStatusChangedEvent(update=update)
        await handler.handle_mount_status_event(event)

        msg = ws_manager.broadcast_message.call_args[0][0]
        assert msg["type"] == "mount_status"
        assert msg["data"]["mount_status"] == "SUCCESS"
        assert msg["data"]["share_url"] == "//nas/share"


class TestIngestEvents:
    @pytest.mark.asyncio
    async def test_ingest_status_updated(self, handler, ws_manager):
        event = IngestStatusUpdatedEvent(
            status_snapshot={"KAM_1": {"is_recording": True}},
            auto_stop_info={"enabled": True},
        )
        await handler.handle_ingest_status_updated_event(event)

        msg = ws_manager.broadcast_message.call_args[0][0]
        assert msg["type"] == "ingest_status_update"
        assert msg["data"]["channels"] == {"KAM_1": {"is_recording": True}}
        assert msg["data"]["auto_stop"]["enabled"] is True

    @pytest.mark.asyncio
    async def test_channel_error_detected(self, handler, ws_manager):
        event = ChannelErrorDetectedEvent(
            channel_name="KAM_1",
            error_message="Signal lost",
            error_code=42,
        )
        await handler.handle_channel_error_detected_event(event)

        msg = ws_manager.broadcast_message.call_args[0][0]
        assert msg["type"] == "channel_error"
        assert msg["data"]["error_code"] == 42

    @pytest.mark.asyncio
    async def test_ingest_online(self, handler, ws_manager):
        event = IngestOnlineEvent()
        await handler.handle_ingest_online_event(event)

        msg = ws_manager.broadcast_message.call_args[0][0]
        assert msg["type"] == "ingest_online"
        assert msg["data"]["is_connected"] is True

    @pytest.mark.asyncio
    async def test_ingest_offline(self, handler, ws_manager):
        event = IngestOfflineEvent()
        await handler.handle_ingest_offline_event(event)

        msg = ws_manager.broadcast_message.call_args[0][0]
        assert msg["type"] == "ingest_offline"
        assert msg["data"]["is_connected"] is False

    @pytest.mark.asyncio
    async def test_recording_paths_discovered(self, handler, ws_manager):
        event = RecordingPathsDiscoveredEvent(
            channel_name="KAM_1",
            preset_name="HD",
            paths=("/path/a", "/path/b"),
        )
        await handler.handle_recording_paths_discovered_event(event)

        msg = ws_manager.broadcast_message.call_args[0][0]
        assert msg["type"] == "recording_paths_update"
        assert msg["data"]["paths"] == ["/path/a", "/path/b"]

    @pytest.mark.asyncio
    async def test_auto_stop_warning(self, handler, ws_manager):
        event = AutoStopWarningEvent(
            channel_name="KAM_1",
            recording_seconds=3400,
            limit_seconds=3600,
            remaining_seconds=200,
        )
        await handler.handle_auto_stop_warning_event(event)

        msg = ws_manager.broadcast_message.call_args[0][0]
        assert msg["type"] == "auto_stop_warning"
        assert msg["data"]["remaining_seconds"] == 200

    @pytest.mark.asyncio
    async def test_auto_stop_triggered(self, handler, ws_manager):
        event = AutoStopTriggeredEvent(
            channel_name="KAM_1",
            recording_seconds=3600,
            limit_seconds=3600,
        )
        await handler.handle_auto_stop_triggered_event(event)

        msg = ws_manager.broadcast_message.call_args[0][0]
        assert msg["type"] == "auto_stop_triggered"
        assert msg["data"]["recording_seconds"] == 3600


class TestTallySwitchEvents:
    @pytest.mark.asyncio
    async def test_tally_switch_status_updated(self, handler, ws_manager):
        status = _make_tally_status()
        prev_status = _make_tally_status(is_online=False)
        event = TallySwitchStatusUpdatedEvent(status=status, previous_status=prev_status)
        await handler.handle_tally_switch_status_updated_event(event)

        msg = ws_manager.broadcast_message.call_args[0][0]
        assert msg["type"] == "tally_switch_status_update"
        assert msg["data"]["is_online"] is True
        assert msg["data"]["status_changed"] is True

    @pytest.mark.asyncio
    async def test_tally_switch_online(self, handler, ws_manager):
        status = _make_tally_status()
        event = TallySwitchOnlineEvent(status=status)
        await handler.handle_tally_switch_online_event(event)

        msg = ws_manager.broadcast_message.call_args[0][0]
        assert msg["type"] == "tally_switch_online"
        assert msg["data"]["is_online"] is True

    @pytest.mark.asyncio
    async def test_tally_switch_offline(self, handler, ws_manager):
        status = _make_tally_status(is_online=False, error_message="Timeout")
        event = TallySwitchOfflineEvent(status=status)
        await handler.handle_tally_switch_offline_event(event)

        msg = ws_manager.broadcast_message.call_args[0][0]
        assert msg["type"] == "tally_switch_offline"
        assert msg["data"]["is_online"] is False
        assert msg["data"]["error_message"] == "Timeout"
