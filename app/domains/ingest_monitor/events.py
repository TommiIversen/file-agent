"""
Ingest Monitor Domain Events

Events published by the ingest monitor service to communicate
channel status changes to other domains (like tally lights).
"""
from dataclasses import dataclass, field
from typing import Dict, List

from app.core.events.domain_event import DomainEvent


@dataclass(frozen=True)
class ChannelRecordingStartedEvent(DomainEvent):
    """Published when a channel starts recording."""
    channel_name: str


@dataclass(frozen=True)
class ChannelRecordingStoppedEvent(DomainEvent):
    """Published when a channel stops recording."""
    channel_name: str


@dataclass(frozen=True)
class ChannelErrorDetectedEvent(DomainEvent):
    """Published when a new error is detected on a channel."""
    channel_name: str
    error_message: str
    error_code: int


@dataclass(frozen=True)
class ChannelSignalLostEvent(DomainEvent):
    """Published when a channel loses video signal."""
    channel_name: str


@dataclass(frozen=True)
class ChannelSignalRestoredEvent(DomainEvent):
    """Published when a channel's video signal is restored."""
    channel_name: str


@dataclass(frozen=True)
class IngestStatusUpdatedEvent(DomainEvent):
    """
    Published periodically with a complete snapshot of all channel statuses.
    
    This is the main event that the Tally Light domain listens to
    for determining the overall recording state.
    """
    status_snapshot: Dict[str, dict] # {"KAM_1": {"is_recording": true, "has_signal": true, ...}}
    auto_stop_info: dict = field(default_factory=dict)  # Auto-stop status for UI countdown


@dataclass(frozen=True)
class IngestOnlineEvent(DomainEvent):
    """Published when ingest monitor successfully connects to Just In Engine."""
    pass


@dataclass(frozen=True)
class IngestOfflineEvent(DomainEvent):
    """Published when ingest monitor loses connection to Just In Engine."""
    pass


@dataclass(frozen=True)
class RecordingPathsDiscoveredEvent(DomainEvent):
    """Published when recording destination paths are discovered from Just In Engine."""
    paths: tuple  # Use tuple for frozen dataclass compatibility
    preset_name: str = ""
    channel_name: str = ""


@dataclass(frozen=True)
class AutoStopWarningEvent(DomainEvent):
    """Published when any channel approaches the auto-stop time limit."""
    channel_name: str  # The channel that triggered the warning
    recording_seconds: int  # Current recording time in seconds
    limit_seconds: int  # The auto-stop limit in seconds
    remaining_seconds: int  # Seconds remaining before auto-stop


@dataclass(frozen=True)
class AutoStopTriggeredEvent(DomainEvent):
    """Published when any channel reaches the auto-stop time limit."""
    channel_name: str  # The channel that triggered the stop
    recording_seconds: int  # Recording time when triggered
    limit_seconds: int  # The configured limit