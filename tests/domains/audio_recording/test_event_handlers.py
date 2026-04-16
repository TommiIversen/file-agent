"""Tests for Audio Recording — Event Handlers.

Covers the channel lifecycle (start/stop), auto-stop, device disconnect,
and the resume/recovery flow.
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.events.audio_events import AudioDeviceDisconnectedEvent
from app.core.events.ingest_events import (
    AutoStopTriggeredEvent,
    ChannelRecordingStartedEvent,
    ChannelRecordingStoppedEvent,
)
from app.domains.audio_recording.event_handlers import AudioRecordingEventHandler


# ── Helpers ───────────────────────────────────────────────────


def _make_handler(
    *,
    is_recording: bool = False,
    session_id: str | None = None,
    device_name: str | None = "ASIO Test",
    use_justin_naming: bool = False,
) -> AudioRecordingEventHandler:
    command_bus = MagicMock()
    command_bus.execute = AsyncMock(return_value={"success": True})
    query_bus = MagicMock()
    query_bus.execute = AsyncMock(return_value=None)

    service = MagicMock()
    service.is_recording = is_recording
    service._current_session_id = session_id
    service._device_name = device_name
    service.invalidate_recorder = AsyncMock()
    service.handle_device_lost = AsyncMock()
    service.reset_recovery_counter = MagicMock()
    service.get_recovery_prefix = MagicMock(side_effect=lambda s: f"{s}_rec2")

    async def get_setting(key: str):
        if key == "audio_filename_from_justin":
            return use_justin_naming
        return None

    handler = AudioRecordingEventHandler(
        command_bus=command_bus,
        query_bus=query_bus,
        service=service,
        get_user_setting=get_setting,
    )
    return handler


def _started_event(channel: str = "KAM_1") -> ChannelRecordingStartedEvent:
    return ChannelRecordingStartedEvent(channel_name=channel)


def _stopped_event(channel: str = "KAM_1") -> ChannelRecordingStoppedEvent:
    return ChannelRecordingStoppedEvent(channel_name=channel)


# ── Channel recording start ──────────────────────────────────


class TestChannelRecordingStarted:
    async def test_first_channel_starts_recording(self):
        h = _make_handler()
        await h.handle_channel_recording_started(_started_event("KAM_1"))

        h._command_bus.execute.assert_awaited_once()
        cmd = h._command_bus.execute.call_args[0][0]
        assert cmd.__class__.__name__ == "StartAudioRecordingCommand"

    async def test_second_channel_ignored(self):
        h = _make_handler()
        await h.handle_channel_recording_started(_started_event("KAM_1"))

        # Now service is_recording — mock it
        h._service.is_recording = True
        h._command_bus.execute.reset_mock()

        await h.handle_channel_recording_started(_started_event("KAM_2"))
        h._command_bus.execute.assert_not_awaited()

    async def test_tracks_active_channels(self):
        h = _make_handler()
        await h.handle_channel_recording_started(_started_event("KAM_1"))
        assert "KAM_1" in h._active_channels

    async def test_stores_trigger_channel(self):
        h = _make_handler()
        await h.handle_channel_recording_started(_started_event("KAM_3"))
        assert h._last_trigger_channel == "KAM_3"


class TestChannelRecordingStopped:
    async def test_last_channel_stops_recording(self):
        h = _make_handler(is_recording=True)
        h._active_channels = {"KAM_1"}
        await h.handle_channel_recording_stopped(_stopped_event("KAM_1"))

        h._command_bus.execute.assert_awaited_once()
        cmd = h._command_bus.execute.call_args[0][0]
        assert cmd.__class__.__name__ == "StopAudioRecordingCommand"

    async def test_other_channels_still_active(self):
        h = _make_handler(is_recording=True)
        h._active_channels = {"KAM_1", "KAM_2"}
        await h.handle_channel_recording_stopped(_stopped_event("KAM_1"))

        h._command_bus.execute.assert_not_awaited()
        assert h._active_channels == {"KAM_2"}

    async def test_noop_when_not_recording(self):
        h = _make_handler(is_recording=False)
        h._active_channels = set()
        await h.handle_channel_recording_stopped(_stopped_event("KAM_1"))
        h._command_bus.execute.assert_not_awaited()

    async def test_resets_recovery_counter(self):
        h = _make_handler(is_recording=True)
        h._active_channels = {"KAM_1"}
        await h.handle_channel_recording_stopped(_stopped_event("KAM_1"))
        h._service.reset_recovery_counter.assert_called_once()


# ── Auto-stop ─────────────────────────────────────────────────


class TestAutoStopTriggered:
    async def test_stops_recording(self):
        h = _make_handler(is_recording=True)
        h._active_channels = {"KAM_1", "KAM_2"}
        await h.handle_auto_stop_triggered(
            AutoStopTriggeredEvent(channel_name="KAM_1", recording_seconds=3600, limit_seconds=3600)
        )
        h._command_bus.execute.assert_awaited_once()
        assert h._active_channels == set()

    async def test_noop_when_not_recording(self):
        h = _make_handler(is_recording=False)
        await h.handle_auto_stop_triggered(
            AutoStopTriggeredEvent(channel_name="KAM_1", recording_seconds=3600, limit_seconds=3600)
        )
        h._command_bus.execute.assert_not_awaited()


# ── Device disconnected ───────────────────────────────────────


class TestDeviceDisconnected:
    async def test_invalidates_recorder(self):
        h = _make_handler()
        await h.handle_device_disconnected(
            AudioDeviceDisconnectedEvent(device_name="ASIO Test")
        )
        h._service.invalidate_recorder.assert_awaited_once()

    async def test_clears_active_channels(self):
        h = _make_handler()
        h._active_channels = {"KAM_1", "KAM_2"}
        await h.handle_device_disconnected(
            AudioDeviceDisconnectedEvent(device_name="ASIO Test")
        )
        assert h._active_channels == set()

    async def test_triggers_resume_when_channels_active(self):
        h = _make_handler()
        h._active_channels = {"KAM_1"}
        h._last_trigger_channel = "KAM_1"

        with patch.object(h, "_attempt_resume", new_callable=AsyncMock) as mock_resume:
            await h.handle_device_disconnected(
                AudioDeviceDisconnectedEvent(device_name="ASIO Test")
            )
        mock_resume.assert_awaited_once_with("KAM_1", {"KAM_1"})

    async def test_no_resume_when_idle(self):
        h = _make_handler()
        h._active_channels = set()

        with patch.object(h, "_attempt_resume", new_callable=AsyncMock) as mock_resume:
            await h.handle_device_disconnected(
                AudioDeviceDisconnectedEvent(device_name="ASIO Test")
            )
        mock_resume.assert_not_awaited()

    async def test_triggers_test_resume_for_test_session(self):
        h = _make_handler(session_id="test-abc123")
        h._active_channels = set()

        with patch.object(h, "_attempt_test_resume", new_callable=AsyncMock) as mock_test:
            await h.handle_device_disconnected(
                AudioDeviceDisconnectedEvent(device_name="ASIO Test")
            )
        mock_test.assert_awaited_once()

    async def test_no_test_resume_for_normal_session(self):
        h = _make_handler(session_id="e29b6dd3-5bbf-4bd7")
        h._active_channels = set()

        with patch.object(h, "_attempt_test_resume", new_callable=AsyncMock) as mock_test:
            await h.handle_device_disconnected(
                AudioDeviceDisconnectedEvent(device_name="ASIO Test")
            )
        mock_test.assert_not_awaited()


# ── _get_filename_stem ─────────────────────────────────────────


class TestGetFilenameStem:
    async def test_local_timestamp_when_justin_disabled(self):
        h = _make_handler(use_justin_naming=False)
        stem, channel = await h._get_filename_stem("KAM_1")
        assert channel is None
        assert len(stem) == 13  # "YYMMDD_HHMMSS"

    async def test_returns_justin_stem_on_success(self):
        h = _make_handler(use_justin_naming=True)
        h._query_bus.execute = AsyncMock(return_value="260416_120000_KAM_1")
        stem, channel = await h._get_filename_stem("KAM_1")
        assert stem == "260416_120000_KAM_1"
        assert channel == "KAM_1"

    async def test_falls_back_to_timestamp_on_failure(self):
        h = _make_handler(use_justin_naming=True)
        h._query_bus.execute = AsyncMock(side_effect=RuntimeError("timeout"))

        # Patch sleep to avoid real delays
        with patch("app.domains.audio_recording.event_handlers.asyncio.sleep", new_callable=AsyncMock):
            stem, channel = await h._get_filename_stem("KAM_1")
        assert channel is None
        assert len(stem) == 13

    async def test_falls_back_when_justin_returns_none(self):
        h = _make_handler(use_justin_naming=True)
        h._query_bus.execute = AsyncMock(return_value=None)

        with patch("app.domains.audio_recording.event_handlers.asyncio.sleep", new_callable=AsyncMock):
            stem, channel = await h._get_filename_stem("KAM_1")
        assert channel is None


# ── _attempt_resume (fast path — mock sleep & device wait) ────


class TestAttemptResume:
    async def test_successful_resume(self):
        h = _make_handler()
        h._last_trigger_channel = "KAM_1"

        with (
            patch.object(h, "_wait_for_device", new_callable=AsyncMock, return_value=True),
            patch("app.domains.audio_recording.event_handlers.asyncio.sleep", new_callable=AsyncMock),
        ):
            await h._attempt_resume("KAM_1", {"KAM_1"})

        h._service.handle_device_lost.assert_awaited_once()
        h._command_bus.execute.assert_awaited_once()
        # Check recovery prefix was used
        h._service.get_recovery_prefix.assert_called_once()

    async def test_device_not_found_gives_up(self):
        h = _make_handler()

        with (
            patch.object(h, "_wait_for_device", new_callable=AsyncMock, return_value=False),
            patch("app.domains.audio_recording.event_handlers.asyncio.sleep", new_callable=AsyncMock),
        ):
            await h._attempt_resume("KAM_1", {"KAM_1"})

        h._command_bus.execute.assert_not_awaited()

    async def test_retries_on_failure(self):
        h = _make_handler()
        h._RESUME_MAX_START_RETRIES = 2
        h._command_bus.execute = AsyncMock(
            side_effect=[{"success": False, "message": "ASIO error"}, {"success": True}]
        )

        with (
            patch.object(h, "_wait_for_device", new_callable=AsyncMock, return_value=True),
            patch("app.domains.audio_recording.event_handlers.asyncio.sleep", new_callable=AsyncMock),
        ):
            await h._attempt_resume("KAM_1", {"KAM_1"})

        assert h._command_bus.execute.await_count == 2

    async def test_restores_channels_on_success(self):
        h = _make_handler()
        original_channels = {"KAM_1", "KAM_2"}

        with (
            patch.object(h, "_wait_for_device", new_callable=AsyncMock, return_value=True),
            patch("app.domains.audio_recording.event_handlers.asyncio.sleep", new_callable=AsyncMock),
        ):
            await h._attempt_resume("KAM_1", original_channels)

        assert h._active_channels == original_channels

    async def test_aborts_if_already_recording(self):
        h = _make_handler()
        h._service.is_recording = True

        with (
            patch.object(h, "_wait_for_device", new_callable=AsyncMock, return_value=True),
            patch("app.domains.audio_recording.event_handlers.asyncio.sleep", new_callable=AsyncMock),
        ):
            await h._attempt_resume("KAM_1", {"KAM_1"})

        h._command_bus.execute.assert_not_awaited()


class TestAttemptTestResume:
    async def test_successful_test_resume(self):
        h = _make_handler()

        with (
            patch.object(h, "_wait_for_device_unconditional", new_callable=AsyncMock, return_value=True),
            patch("app.domains.audio_recording.event_handlers.asyncio.sleep", new_callable=AsyncMock),
        ):
            await h._attempt_test_resume()

        h._service.handle_device_lost.assert_awaited_once()
        h._command_bus.execute.assert_awaited_once()
        cmd = h._command_bus.execute.call_args[0][0]
        assert cmd.session_id.startswith("test-")

    async def test_device_not_found(self):
        h = _make_handler()

        with (
            patch.object(h, "_wait_for_device_unconditional", new_callable=AsyncMock, return_value=False),
            patch("app.domains.audio_recording.event_handlers.asyncio.sleep", new_callable=AsyncMock),
        ):
            await h._attempt_test_resume()

        h._command_bus.execute.assert_not_awaited()


# ── _wait_for_device ──────────────────────────────────────────


class TestWaitForDevice:
    async def test_returns_false_without_device_name(self):
        h = _make_handler(device_name=None)
        result = await h._wait_for_device()
        assert result is False

    async def test_returns_true_when_device_present(self):
        h = _make_handler(device_name="ASIO Test")
        h._last_trigger_channel = "KAM_1"
        h._DEVICE_POLL_MAX_WAIT_S = 1.0

        mock_device = MagicMock()
        mock_device.name = "ASIO Test Device"

        with (
            patch(
                "app.domains.audio_recording.event_handlers.list_available_devices",
                return_value=[mock_device],
                create=True,
            ),
            patch("app.domains.audio_recording.event_handlers.asyncio.sleep", new_callable=AsyncMock),
        ):
            # Patch the import inside the method
            with patch(
                "app.domains.audio_recording.recorder.factory.list_available_devices",
                return_value=[mock_device],
            ):
                result = await h._wait_for_device()

        assert result is True

    async def test_aborts_when_trigger_cleared(self):
        h = _make_handler(device_name="ASIO Test")
        h._last_trigger_channel = None  # already cleared
        h._DEVICE_POLL_MAX_WAIT_S = 1.0

        result = await h._wait_for_device()
        assert result is False


class TestWaitForDeviceUnconditional:
    async def test_returns_false_without_device_name(self):
        h = _make_handler(device_name=None)
        result = await h._wait_for_device_unconditional()
        assert result is False
