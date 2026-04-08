"""
System configuration queries for the shared domain.
These queries handle read-only operations for system settings and configuration.
"""
from dataclasses import dataclass

from app.core.cqrs.query import Query


@dataclass
class GetSettingsQuery(Query):
    """Query to get the current application settings."""
    pass


@dataclass
class GetConfigInfoQuery(Query):
    """Query to get information about the loaded configuration file."""
    pass


@dataclass
class GetUserSettingsQuery(Query):
    """Query to get all user-editable settings with metadata."""
    pass
