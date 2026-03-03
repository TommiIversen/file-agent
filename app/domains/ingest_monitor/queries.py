"""
Ingest Monitor Queries

This module defines queries for retrieving ingest monitor data
following the CQRS pattern.
"""

from dataclasses import dataclass
from app.core.cqrs.query import Query


@dataclass
class GetIngestStatusQuery(Query):
    """
    Query to retrieve the cached snapshot of all channel statuses.
    
    This provides the current state of all Just In Engine channels
    including recording status, signal availability, and error conditions.
    """
    pass # No parameters needed - returns complete status snapshot


@dataclass
class GetRecordingPathsQuery(Query):
    """
    Query to retrieve the discovered recording destination paths.

    Returns the cached result of the 3-step Just In Engine discovery
    flow (recordingConfiguration -> requestDestinationPresets ->
    requestLoadDestinationPreset) per channel.
    """
    pass