"""
Cross-domain query contracts.

Query DTOs that are dispatched by one domain and handled by another.
Follows the same shared-contract pattern as app.core.events.
"""
from dataclasses import dataclass
from app.core.cqrs.query import Query


@dataclass
class GetTallySwitchStatusQuery(Query):
    """Query for tally switch hardware status.

    Dispatched by presentation, handled by tally_light domain.
    """
    pass


@dataclass
class GetIngestConnectionStatusQuery(Query):
    """Query for Just In Engine connection status.

    Dispatched by presentation, handled by ingest_monitor domain.
    """
    pass


@dataclass
class GetCurrentFilenameQuery(Query):
    """Query for the current filename prefix from Just In Engine.

    Dispatched by audio_recording, handled by ingest_monitor domain.
    Returns the prefix string (e.g. "260410_1056_10") or None.
    """
    channel: str
