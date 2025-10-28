from app.core.cqrs.query import Query


class GetStatisticsQuery(Query):
    """A query to retrieve current system statistics."""
    pass


class GetAllFilesQuery(Query):
    """A query to retrieve all tracked files."""
    pass


class GetStorageStatusQuery(Query):
    """A query to retrieve the status of source and destination storage."""
    pass
