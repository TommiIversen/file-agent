"""
Storage monitoring queries for the shared domain.
These queries handle read-only operations for storage status information.
"""
from dataclasses import dataclass

from app.core.cqrs.query import Query


@dataclass
class GetSourceStorageQuery(Query):
    """Query to get source storage information."""
    pass


@dataclass  
class GetDestinationStorageQuery(Query):
    """Query to get destination storage information."""
    pass