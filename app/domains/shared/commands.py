from dataclasses import dataclass

from app.core.cqrs.command import Command


@dataclass
class ReloadConfigCommand(Command):
    """Udløs en genindlæsning af konfigurationsfilen."""
    pass


@dataclass
class RestartApplicationCommand(Command):
    """Udløs en genstart af applikationen."""
    pass