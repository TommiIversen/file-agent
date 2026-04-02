"""
Ingest Monitor Domain Events

Re-exports from app.core.events.ingest_events for backwards compatibility.
Canonical definitions live in core to avoid cross-domain imports.
"""
from app.core.events.ingest_events import (  # noqa: F401
    ChannelRecordingStartedEvent,
    ChannelRecordingStoppedEvent,
    ChannelErrorDetectedEvent,
    ChannelSignalLostEvent,
    ChannelSignalRestoredEvent,
    IngestStatusUpdatedEvent,
    IngestOnlineEvent,
    IngestOfflineEvent,
    RecordingPathsDiscoveredEvent,
    AutoStopWarningEvent,
    AutoStopTriggeredEvent,
)