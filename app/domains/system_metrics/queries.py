from dataclasses import dataclass

from app.core.cqrs.query import Query


@dataclass
class GetPerformanceHistoryQuery(Query):
    """Query to retrieve the performance metrics time-series history."""

    pass
