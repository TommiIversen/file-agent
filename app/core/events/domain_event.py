"""
Base class for all domain events.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """
    Represents an event that occurred in the domain.

    Attributes:
        event_id: A unique identifier for the event instance.
        timestamp: The UTC time when the event was created.
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
