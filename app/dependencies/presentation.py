"""
Presentation factories.

WebSocketManager, PresentationEventHandlers.
"""
from app.dependencies.core import (
    _singletons,
    get_file_repository,
)
from app.domains.presentation.websocket_manager import WebSocketManager
from app.domains.presentation.event_handlers import PresentationEventHandlers


def get_websocket_manager() -> WebSocketManager:
    """Gets the singleton instance of the pure WebSocketManager."""
    if "websocket_manager" not in _singletons:
        _singletons["websocket_manager"] = WebSocketManager()
    return _singletons["websocket_manager"]


def get_presentation_event_handlers() -> PresentationEventHandlers:
    if "presentation_event_handlers" not in _singletons:
        _singletons["presentation_event_handlers"] = PresentationEventHandlers(
            websocket_manager=get_websocket_manager(),
            file_repository=get_file_repository(),
        )
    return _singletons["presentation_event_handlers"]
