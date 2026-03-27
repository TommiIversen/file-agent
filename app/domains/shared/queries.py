from dataclasses import dataclass

from app.core.cqrs.query import Query


@dataclass
class GetSettingsQuery(Query):
    """Hent de nuværende applikations-settings."""
    pass


@dataclass
class GetConfigInfoQuery(Query):
    """Hent info om den indlæste konfigurationsfil."""
    pass