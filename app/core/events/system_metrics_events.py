from dataclasses import dataclass, field
from typing import Any

from app.core.events.domain_event import DomainEvent


@dataclass(frozen=True)
class SystemMetricsUpdatedEvent(DomainEvent):
    """Published every metrics collection cycle with the latest sample."""

    sample: dict[str, Any] = field(default_factory=dict)
