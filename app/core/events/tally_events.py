"""
Tally Light Domain Events

Public event contracts for the tally light domain.
"""
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

from app.core.events.domain_event import DomainEvent


@dataclass
class TallySwitchStatus:
    """Represents the current status of a tally switch.
    
    Defined in core as part of the event contract between domains.
    """
    is_online: bool
    switch_type: str
    ip_address: str
    last_checked: datetime
    error_message: Optional[str] = None


@dataclass(frozen=True)
class TallySwitchOnlineEvent(DomainEvent):
    """Event fired when tally switch comes online."""
    status: TallySwitchStatus


@dataclass(frozen=True)
class TallySwitchOfflineEvent(DomainEvent):
    """Event fired when tally switch goes offline."""
    status: TallySwitchStatus


@dataclass(frozen=True)
class TallySwitchStatusUpdatedEvent(DomainEvent):
    """Event fired on any status update (online/offline)."""
    status: TallySwitchStatus
    previous_status: Optional[TallySwitchStatus] = None

    @property
    def status_changed(self) -> bool:
        return (
            self.previous_status is None or
            self.previous_status.is_online != self.status.is_online
        )
