from dataclasses import dataclass


@dataclass
class GetSettingsQuery:
    """Hent de nuværende applikations-settings."""
    pass


@dataclass
class GetConfigInfoQuery:
    """Hent info om den indlæste konfigurationsfil."""
    pass