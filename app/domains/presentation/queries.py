from dataclasses import dataclass, field
from typing import Optional

from app.core.cqrs.query import Query


class GetStatisticsQuery(Query):
    """A query to retrieve current system statistics."""
    pass


class GetAllFilesQuery(Query):
    """A query to retrieve all tracked files."""
    pass


@dataclass
class GetRecentFilesQuery(Query):
    """A query to retrieve recent files with pagination."""
    limit: int = 20
    offset: int = 0
    status: Optional[str] = None


class GetStorageStatusQuery(Query):
    """A query to retrieve the status of source and destination storage."""
    pass
