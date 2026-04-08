from dataclasses import dataclass, field
from typing import Any

from app.core.cqrs.command import Command


@dataclass
class ReloadConfigCommand(Command):
    """Udløs en genindlæsning af konfigurationsfilen."""
    pass


@dataclass
class RestartApplicationCommand(Command):
    """Udløs en genstart af applikationen."""
    pass


@dataclass
class UpdateUserSettingsCommand(Command):
    """Update one or more user-editable settings in the database."""
    updates: dict[str, Any] = field(default_factory=dict)
