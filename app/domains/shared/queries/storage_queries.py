"""
Storage monitoring queries for the shared domain.
These queries handle read-only operations for storage status information.
"""
from dataclasses import dataclass


@dataclass
class GetSourceStorageQuery:
    """Query to get source storage information."""
    pass


@dataclass  
class GetDestinationStorageQuery:
    """Query to get destination storage information."""
    pass