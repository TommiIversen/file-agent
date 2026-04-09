"""
Lifecycle Domain Registration
Register all commands and handlers for the lifecycle domain.
"""
import logging

from app.core.cqrs.command_bus import CommandBus
from app.dependencies.core import get_file_repository
from .commands import PruneOldFilesCommand
from .handlers import PruneOldFilesCommandHandler


def register_lifecycle_domain(command_bus: CommandBus) -> None:
    """
    Register all lifecycle domain handlers with the command bus.
    
    This function is responsible solely for wiring up the lifecycle
    domain's command handlers to the CQRS infrastructure.
    """
    logging.info("Registering 'Lifecycle' domain handlers...")

    # Create handler with dependency injection
    handler = PruneOldFilesCommandHandler(
        file_repository=get_file_repository()
    )
    
    # Register command handler
    command_bus.register(PruneOldFilesCommand, handler.handle)
    
    logging.info("Lifecycle domain handlers registered successfully")