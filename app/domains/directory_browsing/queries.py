from dataclasses import dataclass
from app.core.cqrs.query import Query

# Query for at scanne kilde-mappen
@dataclass(frozen=True)
class ScanSourceDirectoryQuery(Query):
    recursive: bool
    max_depth: int

# Query for at scanne destinations-mappen
@dataclass(frozen=True)
class ScanDestinationDirectoryQuery(Query):
    recursive: bool
    max_depth: int

# Query for at scanne en brugerdefineret mappe
@dataclass(frozen=True)
class ScanCustomDirectoryQuery(Query):
    path: str
    recursive: bool
    max_depth: int

# Query for at hente service-info
@dataclass(frozen=True)
class GetScannerInfoQuery(Query):
    pass