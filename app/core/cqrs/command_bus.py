import logging
from typing import Dict, Type, Callable, Awaitable, Any
from app.core.cqrs.command import Command  # Importerer baseklassen

logger = logging.getLogger(__name__)

class CommandBus:
    """
    En simpel command bus, der sender commands til registrerede handlers.
    Sikrer, at hver command-type kun håndteres af præcis én handler (1-til-1).
    """
    def __init__(self):
        self._handlers: Dict[Type[Command], Callable[[Command], Awaitable[Any]]] = {}

    def register(self, command_type: Type[Command], handler: Callable[[Command], Awaitable[Any]]):
        """
        Registrerer en handler til en specifik command-type.
        Kaster en ValueError, hvis en handler allerede er registreret.
        """
        if command_type in self._handlers:
            logger.error(f"Handler for command '{command_type.__name__}' er allerede registreret.")
            raise ValueError(f"Handler for command '{command_type.__name__}' er allerede registreret.")
        
        self._handlers[command_type] = handler
        logger.debug(f"Handler {handler.__name__} registreret for {command_type.__name__}")

    def is_registered(self, command_type: Type[Command]) -> bool:
        """
        Checker om en handler allerede er registreret for en command-type.
        """
        return command_type in self._handlers

    async def execute(self, command: Command) -> Any:
        """
        Eksekverer en command ved at sende den til den registrerede handler.
        Kaster en ValueError, hvis ingen handler er fundet.
        """
        handler = self._handlers.get(type(command))
        if not handler:
            logger.error(f"Ingen handler registreret for command '{type(command).__name__}'")
            raise ValueError(f"No handler registered for command '{type(command).__name__}'")
        
        # Kald den asynkrone handler og returner (hvis der er) et resultat
        return await handler(command)