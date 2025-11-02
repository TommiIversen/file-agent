from dataclasses import dataclass
from app.core.events.domain_event import DomainEvent
from app.models import StorageUpdate, MountStatusUpdate, StorageInfo

@dataclass(frozen=True)
class StorageStatusChangedEvent(DomainEvent):
    """Event published when storage status changes."""
    update: StorageUpdate

@dataclass(frozen=True)
class MountStatusChangedEvent(DomainEvent):
    """Event published when mount status changes."""
    update: MountStatusUpdate

@dataclass(frozen=True)
class DestinationUnavailableEvent(DomainEvent):
    """Publiceres når destinationen går fra OK -> ERROR/CRITICAL."""
    reason: str
    storage_info: StorageInfo

@dataclass(frozen=True)
class DestinationRecoveredEvent(DomainEvent):
    """Publiceres når destinationen går fra ERROR/CRITICAL -> OK."""
    reason: str
    storage_info: StorageInfo

@dataclass(frozen=True)
class NetworkFailureDetectedEvent(DomainEvent):
    """Publiceres når NetworkErrorDetector finder en netværksfejl under kopiering."""
    error_message: str
    file_id: str
    operation: str

@dataclass(frozen=True)
class NetworkStatusChanged(DomainEvent):
    """Autoritativ event fra NetworkCoordinator om netværksstatus ændringer."""
    available: bool
    reason: str
    source: str  # "periodic_check" | "copy_failure" | "recovery"