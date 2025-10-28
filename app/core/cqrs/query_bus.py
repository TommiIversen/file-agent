import logging
from typing import Dict, Type, Callable, Awaitable, Any
from app.core.cqrs.query import Query

# Logger til at spore bus-aktivitet
logger = logging.getLogger(__name__)

class QueryBus:
    """
    En simpel, asynkron Query Bus (Mediator-mønster).
    
    Den router en Query til præcis én registreret Handler.
    Dette er en 1-til-1 mekanisme.
    """

    def __init__(self):
        # Holder styr på: {QueryType -> handler_funktion}
        self._handlers: Dict[Type[Query], Callable[[Query], Awaitable[Any]]] = {}

    def register(self, query_type: Type[Query], handler: Callable[[Query], Awaitable[Any]]):
        """
        Registrerer én unik handler til én specifik query-type.
        
        Kaster en fejl, hvis en handler allerede er registreret for denne query,
        for at håndhæve 1-til-1-reglen.
        """
        if query_type in self._handlers:
            logger.error(f"En handler for query '{query_type.__name__}' er allerede registreret.")
            raise ValueError(f"Handler for query '{query_type.__name__}' er allerede registreret.")
        
        self._handlers[query_type] = handler
        logger.debug(f"Handler '{handler.__name__}' registreret for '{query_type.__name__}'")

    async def execute(self, query: Query) -> Any:
        """
        Eksekverer en query ved at finde og kalde dens registrerede handler.
        
        Returnerer resultatet fra handleren.
        Kaster en fejl, hvis ingen handler er fundet.
        """
        query_type = type(query)
        handler = self._handlers.get(query_type)
        
        if not handler:
            logger.error(f"Ingen handler fundet for query '{query_type.__name__}'")
            raise ValueError(f"No handler registered for query '{query_type.__name__}'")

        logger.debug(f"Eksekverer query '{query_type.__name__}' med handler '{handler.__name__}'")
        
        try:
            return await handler(query)
        except Exception as e:
            # Logger fejlen, men lader den kaste videre op til kalderen (API'en)
            # så den kan returnere en pæn HTTP 500-fejl.
            logger.error(
                f"Fejl i handler '{handler.__name__}' ved eksekvering af '{query_type.__name__}': {e}", 
                exc_info=True
            )
            raise