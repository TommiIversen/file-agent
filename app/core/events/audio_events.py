"""
Audio Recording Domain Events

Published by the audio_recording domain to communicate recording state
changes to other domains (presentation, file_discovery, etc.).
"""

from dataclasses import dataclass
from typing import List, Optional

from app.core.events.domain_event import DomainEvent


@dataclass(frozen=True)
class AudioRecordingStartedEvent(DomainEvent):
    """Published when audio recording starts successfully."""

    session_id: str
    tracks: List[str]
    samplerate: int
    files: List[str]


@dataclass(frozen=True)
class AudioRecordingStoppedEvent(DomainEvent):
    """Published when audio recording stops (clean stop)."""

    session_id: str
    files: List[str]
    duration_seconds: float
    overflow_count: int = 0


@dataclass(frozen=True)
class AudioRecordingErrorEvent(DomainEvent):
    """Published when an audio recording error occurs."""

    error: str
    recoverable: bool
    session_id: Optional[str] = None


@dataclass(frozen=True)
class AudioDeviceDisconnectedEvent(DomainEvent):
    """Published when the audio device disappears (USB unplug, driver crash)."""

    device_name: str


@dataclass(frozen=True)
class AudioOverflowWarningEvent(DomainEvent):
    """Published when the audio buffer overflows (writer can't keep up)."""

    dropped_count: int
    total_drops: int
    session_id: Optional[str] = None
