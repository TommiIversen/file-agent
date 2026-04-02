"""
Tally Light Domain Events

Re-exports from app.core.events.tally_events for backwards compatibility.
Canonical definitions live in core to avoid cross-domain imports.
"""
from app.core.events.tally_events import (  # noqa: F401
    TallySwitchStatus,
    TallySwitchOnlineEvent,
    TallySwitchOfflineEvent,
    TallySwitchStatusUpdatedEvent,
)
