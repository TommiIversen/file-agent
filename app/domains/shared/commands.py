from dataclasses import dataclass


@dataclass
class ReloadConfigCommand:
    """Udløs en genindlæsning af konfigurationsfilen."""
    pass


@dataclass
class RestartApplicationCommand:
    """Udløs en genstart af applikationen."""
    pass