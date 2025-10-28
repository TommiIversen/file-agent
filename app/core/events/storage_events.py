from dataclasses import dataclass
from app.core.events.domain_event import DomainEvent
from app.models import StorageInfo, StorageUpdate, MountStatusUpdate

@dataclass(frozen=True)
class StorageStatusChangedEvent(DomainEvent):
    """Event published when storage status changes."""
    update: StorageUpdate

@dataclass(frozen=True)
class MountStatusChangedEvent(DomainEvent):
    """Event published when mount status changes."""
    update: MountStatusUpdate