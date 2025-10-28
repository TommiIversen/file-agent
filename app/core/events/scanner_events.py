# app/core/events/scanner_events.py
from dataclasses import dataclass
from app.core.events.domain_event import DomainEvent

@dataclass(frozen=True)
class ScannerStatusChangedEvent(DomainEvent):
    """Event published when the file scanner starts, stops, pauses, or resumes."""
    is_scanning: bool
    is_paused: bool