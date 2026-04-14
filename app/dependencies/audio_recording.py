"""
Audio recording factories.

AudioRecordingService, recorder instance.

NOTE: The service is created without a recorder instance.
The recorder is injected later when audio settings are configured (Fase 3).
Until then, start() will return "No recorder configured".
"""

from app.dependencies.core import (
    _singletons,
    get_event_bus,
)
from app.domains.audio_recording.service import AudioRecordingService


def get_audio_recording_service() -> AudioRecordingService:
    """Get the AudioRecordingService singleton."""
    if "audio_recording_service" not in _singletons:
        _singletons["audio_recording_service"] = AudioRecordingService(
            event_bus=get_event_bus(),
        )
    return _singletons["audio_recording_service"]
