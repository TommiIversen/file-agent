"""Tests for Audio Recording — Command Handlers."""
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.domains.audio_recording.command_handlers import (
    StartAudioRecordingCommandHandler,
    StopAudioRecordingCommandHandler,
    _parse_tracks,
)
from app.domains.audio_recording.commands import (
    StartAudioRecordingCommand,
    StopAudioRecordingCommand,
)


VALID_TRACKS_JSON = json.dumps([
    {"channels": [1], "label": "Mic1", "mode": "mono"},
    {"channels": [3, 4], "label": "PGM_LR", "mode": "stereo"},
])


def _make_get_setting(**overrides):
    """Create an async setting getter with sane defaults."""
    defaults = {
        "audio_recording_enabled": True,
        "audio_device_name": "ASIO Test Device",
        "audio_sample_rate": 48000,
        "audio_tracks": VALID_TRACKS_JSON,
        "source_directory": "/tmp/input",
    }
    defaults.update(overrides)

    async def get_setting(key: str):
        return defaults.get(key)

    return get_setting


@pytest.fixture
def service():
    svc = MagicMock()
    svc.get_recovery_prefix = MagicMock(side_effect=lambda s: s)
    svc.start = AsyncMock(return_value=[Path("/tmp/input/test_Mic1.wav")])
    svc.stop = AsyncMock(return_value={"status": "stopped", "overflow_count": 0, "duration_seconds": 5.0})
    svc.is_recording = False
    return svc


# ── StartAudioRecordingCommandHandler ─────────────────────────


class TestStartAudioSuccess:
    async def test_starts_recording(self, service):
        handler = StartAudioRecordingCommandHandler(service=service, get_user_setting=_make_get_setting())
        result = await handler.handle(
            StartAudioRecordingCommand(filename_stem="260416_TEST", channel_name=None, session_id="s1")
        )
        assert result["success"] is True
        assert result["session_id"] == "s1"
        service.start.assert_awaited_once()

    async def test_passes_tracks_and_samplerate(self, service):
        handler = StartAudioRecordingCommandHandler(service=service, get_user_setting=_make_get_setting())
        await handler.handle(
            StartAudioRecordingCommand(filename_stem="stem", channel_name="KAM_1", session_id="s1")
        )
        call_kwargs = service.start.call_args
        assert call_kwargs.kwargs["samplerate"] == 48000
        assert len(call_kwargs.kwargs["tracks"]) == 2

    async def test_uses_recovery_prefix(self, service):
        service.get_recovery_prefix = MagicMock(return_value="stem_rec2")
        handler = StartAudioRecordingCommandHandler(service=service, get_user_setting=_make_get_setting())
        await handler.handle(
            StartAudioRecordingCommand(filename_stem="stem", channel_name=None, session_id="s1")
        )
        call_kwargs = service.start.call_args
        assert call_kwargs.kwargs["filename_stem"] == "stem_rec2"


class TestStartAudioDisabled:
    async def test_disabled_returns_failure(self, service):
        handler = StartAudioRecordingCommandHandler(
            service=service,
            get_user_setting=_make_get_setting(audio_recording_enabled=False),
        )
        result = await handler.handle(
            StartAudioRecordingCommand(filename_stem="stem", channel_name=None, session_id="s1")
        )
        assert result["success"] is False
        assert "disabled" in result["message"]
        service.start.assert_not_awaited()


class TestStartAudioMissingConfig:
    async def test_no_device(self, service):
        handler = StartAudioRecordingCommandHandler(
            service=service,
            get_user_setting=_make_get_setting(audio_device_name=""),
        )
        result = await handler.handle(
            StartAudioRecordingCommand(filename_stem="stem", channel_name=None, session_id="s1")
        )
        assert result["success"] is False
        assert "device" in result["message"].lower()

    async def test_no_tracks(self, service):
        handler = StartAudioRecordingCommandHandler(
            service=service,
            get_user_setting=_make_get_setting(audio_tracks="[]"),
        )
        result = await handler.handle(
            StartAudioRecordingCommand(filename_stem="stem", channel_name=None, session_id="s1")
        )
        assert result["success"] is False
        assert "tracks" in result["message"].lower()

    async def test_no_source_dir(self, service):
        handler = StartAudioRecordingCommandHandler(
            service=service,
            get_user_setting=_make_get_setting(source_directory=""),
        )
        result = await handler.handle(
            StartAudioRecordingCommand(filename_stem="stem", channel_name=None, session_id="s1")
        )
        assert result["success"] is False
        assert "source" in result["message"].lower() or "directory" in result["message"].lower()


class TestStartAudioError:
    async def test_service_exception(self, service):
        service.start.side_effect = RuntimeError("ASIO error -1000")
        handler = StartAudioRecordingCommandHandler(service=service, get_user_setting=_make_get_setting())
        result = await handler.handle(
            StartAudioRecordingCommand(filename_stem="stem", channel_name=None, session_id="s1")
        )
        assert result["success"] is False
        assert "ASIO" in result["message"]


# ── StopAudioRecordingCommandHandler ──────────────────────────


class TestStopAudio:
    async def test_stops_recording(self, service):
        handler = StopAudioRecordingCommandHandler(service=service)
        result = await handler.handle(StopAudioRecordingCommand())
        assert result["success"] is True
        assert result["status"] == "stopped"

    async def test_stop_when_not_recording(self, service):
        service.stop.return_value = {"status": "not_recording"}
        handler = StopAudioRecordingCommandHandler(service=service)
        result = await handler.handle(StopAudioRecordingCommand())
        assert result["success"] is True
        assert result["status"] == "not_recording"

    async def test_stop_error(self, service):
        service.stop.side_effect = RuntimeError("stream error")
        handler = StopAudioRecordingCommandHandler(service=service)
        result = await handler.handle(StopAudioRecordingCommand())
        assert result["success"] is False


# ── _parse_tracks ─────────────────────────────────────────────


class TestParseTracks:
    def test_valid_tracks(self):
        tracks = _parse_tracks(VALID_TRACKS_JSON)
        assert len(tracks) == 2
        assert tracks[0].label == "Mic1"
        assert tracks[0].channels == (1,)
        assert tracks[1].label == "PGM_LR"
        assert tracks[1].channels == (3, 4)

    def test_empty_list(self):
        assert _parse_tracks("[]") == []

    def test_invalid_json(self):
        assert _parse_tracks("not json") == []

    def test_none_input(self):
        assert _parse_tracks(None) == []

    def test_missing_key(self):
        tracks = _parse_tracks(json.dumps([{"channels": [1], "label": "X"}]))
        assert tracks == []  # missing 'mode'

    def test_mixed_valid_invalid(self):
        raw = [
            {"channels": [1], "label": "Good", "mode": "mono"},
            {"bad": "entry"},
        ]
        tracks = _parse_tracks(json.dumps(raw))
        assert len(tracks) == 1
        assert tracks[0].label == "Good"
