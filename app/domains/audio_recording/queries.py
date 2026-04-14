"""
Audio Recording — Domain Queries (CQRS)
"""

from dataclasses import dataclass

from app.core.cqrs.query import Query


@dataclass
class GetAudioDevicesQuery(Query):
    """List available audio input devices for the current platform."""

    pass


@dataclass
class GetAudioRecordingStatusQuery(Query):
    """Get current audio recording status (recording, duration, files, etc.)."""

    pass


@dataclass
class GetAudioTrackConfigQuery(Query):
    """Get the configured track list from user settings."""

    pass
