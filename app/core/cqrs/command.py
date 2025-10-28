from abc import ABC, abstractmethod
from typing import Generic, TypeVar, Any, Awaitable

# TCommand begrænses til at være en subklasse af Command
TCommand = TypeVar('TCommand', bound='Command')
# TResult kan være Any, da en command ikke altid returnerer noget
TResult = TypeVar('TResult')


class Command(ABC):
    """Baseklasse for alle commands. En command er en DTO, der repræsenterer en skrive-handling."""
    pass


class CommandHandler(Generic[TCommand, TResult], ABC):
    """
    Baseklasse for en command handler.
    Den tager en specifik TCommand og returnerer (valgfrit) en TResult.
    """
    @abstractmethod
    async def handle(self, command: TCommand) -> TResult:
        """Håndterer den givne command."""
        raise NotImplementedError