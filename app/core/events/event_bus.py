"""
Central domain event bus (Mediator Pattern).
"""
import asyncio
import logging
from collections import defaultdict
from typing import Callable, List, Type, Dict

from app.core.events.domain_event import DomainEvent

# Define a type hint for an event handler
# An event handler is an async function that takes a DomainEvent and returns None
EventHandler = Callable[[DomainEvent], asyncio.Future[None]]

class DomainEventBus:
    """
    A robust, asynchronous event bus for domain event propagation.

    This implementation ensures that if one event handler fails, it does not
    prevent other handlers from being executed. It logs errors from failed
    handlers without stopping the entire event publication process.
    """

    def __init__(self) -> None:
        self._handlers: Dict[Type[DomainEvent], List[EventHandler]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def subscribe(self, event_type: Type[DomainEvent], handler: EventHandler) -> None:
        """
        Subscribes a handler to a specific event type.

        Args:
            event_type: The class of the domain event to subscribe to.
            handler: The asynchronous function to call when the event is published.
        """
        async with self._lock:
            self._handlers[event_type].append(handler)
            logging.debug(f"Handler {handler.__name__} subscribed to {event_type.__name__}")

    async def publish(self, event: DomainEvent) -> None:
        """
        Publishes a domain event, calling all subscribed handlers.

        Executes all handlers concurrently and gathers the results. If a handler
        raises an exception, it is logged, and other handlers continue to execute.

        Args:
            event: The domain event instance to publish.
        """
        event_type = type(event)
        handlers = self._handlers.get(event_type, [])
        
        if not handlers:
            logging.debug(f"No handlers for event {event_type.__name__}")
            return

        logging.info(f"Publishing {event_type.__name__} to {len(handlers)} handler(s)")

        # Create a list of tasks to run all handlers concurrently
        tasks = [self._safe_execute(handler, event) for handler in handlers]
        
        # Wait for all handlers to complete
        await asyncio.gather(*tasks)

    async def _safe_execute(self, handler: EventHandler, event: DomainEvent) -> None:
        """
        Executes a single event handler safely, catching and logging any exceptions.
        """
        try:
            await handler(event)
        except Exception as e:
            logging.error(
                f"Unhandled exception in handler '{handler.__name__}' for event "
                f"'{type(event).__name__}': {e}",
                exc_info=True  # Include stack trace in the log
            )
