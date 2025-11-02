"""
System configuration queries for the shared domain.
These queries handle read-only operations for system settings and configuration.
"""
from dataclasses import dataclass


@dataclass
class GetSettingsQuery:
    """Query to get the current application settings."""
    pass


@dataclass
class GetConfigInfoQuery:
    """Query to get information about the loaded configuration file."""
    pass