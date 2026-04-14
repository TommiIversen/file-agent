"""
Audio Recording — Command Handlers
"""

import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Dict, List

from app.core.cqrs.command import CommandHandler
from app.domains.audio_recording.commands import (
    StartAudioRecordingCommand,
    StopAudioRecordingCommand,
)
from app.domains.audio_recording.recorder.models import AudioTrack
from app.domains.audio_recording.service import AudioRecordingService

logger = logging.getLogger(__name__)


class StartAudioRecordingCommandHandler(CommandHandler[StartAudioRecordingCommand, Dict[str, Any]]):
    """Starts audio recording using configured tracks, device, and sample rate."""

    def __init__(
        self,
        service: AudioRecordingService,
        get_user_setting: Callable[[str], Awaitable[Any]],
    ) -> None:
        self._service = service
        self._get_user_setting = get_user_setting

    async def handle(self, command: StartAudioRecordingCommand) -> Dict[str, Any]:
        try:
            enabled = await self._get_user_setting("audio_recording_enabled")
            if not enabled:
                return {"success": False, "message": "Audio recording is disabled"}

            device_name = await self._get_user_setting("audio_device_name")
            if not device_name:
                return {"success": False, "message": "No audio device configured"}

            samplerate = await self._get_user_setting("audio_sample_rate") or 48000

            tracks_json = await self._get_user_setting("audio_tracks") or "[]"
            tracks = _parse_tracks(tracks_json)
            if not tracks:
                return {"success": False, "message": "No audio tracks configured"}

            source_dir = await self._get_user_setting("source_directory") or ""
            if not source_dir:
                return {"success": False, "message": "No source directory configured"}

            prefix = self._service.get_recovery_prefix(command.filename_prefix)

            files = await self._service.start(
                session_id=command.session_id,
                filename_prefix=prefix,
                tracks=tracks,
                samplerate=samplerate,
                output_dir=Path(source_dir),
            )
            return {
                "success": True,
                "files": [str(f) for f in files],
                "session_id": command.session_id,
            }

        except Exception as e:
            logger.error("Failed to start audio recording: %s", e, exc_info=True)
            return {"success": False, "message": str(e)}


class StopAudioRecordingCommandHandler(CommandHandler[StopAudioRecordingCommand, Dict[str, Any]]):
    """Stops the active audio recording session."""

    def __init__(self, service: AudioRecordingService) -> None:
        self._service = service

    async def handle(self, command: StopAudioRecordingCommand) -> Dict[str, Any]:
        try:
            result = await self._service.stop()
            return {"success": True, **result}
        except Exception as e:
            logger.error("Failed to stop audio recording: %s", e, exc_info=True)
            return {"success": False, "message": str(e)}


def _parse_tracks(tracks_json: str) -> List[AudioTrack]:
    """Parse the JSON track config from user settings."""
    try:
        raw = json.loads(tracks_json)
    except (json.JSONDecodeError, TypeError):
        logger.error("Invalid audio_tracks JSON: %s", tracks_json)
        return []

    tracks: List[AudioTrack] = []
    for item in raw:
        try:
            tracks.append(
                AudioTrack(
                    channels=tuple(item["channels"]),
                    label=item["label"],
                    mode=item["mode"],
                )
            )
        except (KeyError, ValueError) as e:
            logger.error("Invalid track config %s: %s", item, e)
    return tracks
