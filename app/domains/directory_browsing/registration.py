# app/domains/directory_browsing/registration.py
import logging
from app.core.cqrs.query_bus import QueryBus
from app.core.cqrs.command_bus import CommandBus
from app.dependencies import get_directory_scanner

# Importer de queries og handlers, som dette domæne ejer
from .queries import (
    ScanSourceDirectoryQuery,
    ScanDestinationDirectoryQuery,
    ScanCustomDirectoryQuery,
    GetScannerInfoQuery,
)
from .handlers import (
    ScanSourceDirectoryHandler,
    ScanDestinationDirectoryHandler,
    ScanCustomDirectoryHandler,
    GetScannerInfoHandler,
)

def register_directory_browsing_handlers(query_bus: QueryBus, command_bus: CommandBus):
    """
    Registrerer alle queries og commands for 'directory_browsing'-domænet.
    Denne funktion kaldes én gang ved app-opstart fra main.py.
    """
    logging.info("Registrerer 'Directory Browsing' handlers...")
    
    # 1. Hent de afhængigheder, som dette domænes handlers skal bruge
    scanner_service = get_directory_scanner()

    # 2. Registrer alle Query Handlers
    query_bus.register(
        ScanSourceDirectoryQuery,
        ScanSourceDirectoryHandler(scanner_service).handle
    )
    query_bus.register(
        ScanDestinationDirectoryQuery,
        ScanDestinationDirectoryHandler(scanner_service).handle
    )
    query_bus.register(
        ScanCustomDirectoryQuery,
        ScanCustomDirectoryHandler(scanner_service).handle
    )
    query_bus.register(
        GetScannerInfoQuery,
        GetScannerInfoHandler(scanner_service).handle
    )
    
    # 3. (Dette domæne har ingen Command Handlers endnu)