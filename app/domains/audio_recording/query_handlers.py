"""
Audio Recording — Query Handlers
"""

from collections.abc import Awaitable, Callable
from typing import Any, Dict, List

from app.core.cqrs.query import QueryHandler
from app.domains.audio_recording.queries import (
    GetAudioDevicesQuery,
    GetAudioRecordingStatusQuery,
    GetAudioTrackConfigQuery,
)
from app.domains.audio_recording.service import AudioRecordingService


class GetAudioDevicesQueryHandler(QueryHandler[GetAudioDevicesQuery, List[Dict[str, Any]]]):
    """Returns available audio input devices."""

    def __init__(self, service: AudioRecordingService) -> None:
        self._service = service

    async def handle(self, query: GetAudioDevicesQuery) -> List[Dict[str, Any]]:
        devices = await self._service.list_devices()
        return [
            {
                "index": d.index,
                "name": d.name,
                "max_input_channels": d.max_input_channels,
                "default_samplerate": d.default_samplerate,
                "host_api": d.host_api,
            }
            for d in devices
        ]


class GetAudioRecordingStatusQueryHandler(QueryHandler[GetAudioRecordingStatusQuery, Dict[str, Any]]):
    """Returns current recording status."""

    def __init__(self, service: AudioRecordingService) -> None:
        self._service = service

    async def handle(self, query: GetAudioRecordingStatusQuery) -> Dict[str, Any]:
        return self._service.get_status()


class GetAudioTrackConfigQueryHandler(QueryHandler[GetAudioTrackConfigQuery, str]):
    """Returns the raw track config JSON from user settings."""

    def __init__(self, get_user_setting: Callable[[str], Awaitable[Any]]) -> None:
        self._get_user_setting = get_user_setting

    async def handle(self, query: GetAudioTrackConfigQuery) -> str:
        return await self._get_user_setting("audio_tracks") or "[]"
