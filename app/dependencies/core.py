"""
Core infrastructure factories.

Settings, buses, repository, state machine, event store.
"""
import asyncio
from functools import lru_cache
from typing import Any

from app.core.events.event_bus import DomainEventBus
from app.core.file_repository import FileRepository
from app.core.sqlite_file_repository import SqliteFileRepository
from app.core.sqlite_event_store import SqliteEventStore
from app.core.file_state_machine import FileStateMachine
from app.core.cqrs.command_bus import CommandBus
from app.core.cqrs.query_bus import QueryBus
from app.core.global_event_logger import GlobalEventLogger
from app.domains.shared.settings_service import UserSettingsService
from app.config import Settings

# Global singleton instances (shared across all dependency modules)
_singletons: dict[str, Any] = {}


@lru_cache
def get_settings() -> Settings:
    """Hent Settings singleton instance."""
    return Settings()


def get_command_bus() -> CommandBus:
    if "command_bus" not in _singletons:
        _singletons["command_bus"] = CommandBus()
    return _singletons["command_bus"]


def get_query_bus() -> QueryBus:
    if "query_bus" not in _singletons:
        _singletons["query_bus"] = QueryBus()
    return _singletons["query_bus"]


def get_event_bus() -> DomainEventBus:
    if "event_bus" not in _singletons:
        _singletons["event_bus"] = DomainEventBus()
    return _singletons["event_bus"]


def get_file_repository() -> SqliteFileRepository:
    if "file_repository" not in _singletons:
        settings = get_settings()
        _singletons["file_repository"] = SqliteFileRepository(settings.database_path)
    return _singletons["file_repository"]


def get_file_state_machine() -> FileStateMachine:
    if "file_state_machine" not in _singletons:
        _singletons["file_state_machine"] = FileStateMachine(
            file_repository=get_file_repository(),
            event_bus=get_event_bus()
        )
    return _singletons["file_state_machine"]


def get_global_event_logger() -> GlobalEventLogger:
    """Get the GlobalEventLogger singleton for UI event visibility."""
    if "global_event_logger" not in _singletons:
        _singletons["global_event_logger"] = GlobalEventLogger()
    return _singletons["global_event_logger"]


def get_event_store() -> SqliteEventStore:
    """Get the SqliteEventStore singleton, sharing the DB connection from FileRepository."""
    if "event_store" not in _singletons:
        file_repo = get_file_repository()
        _singletons["event_store"] = SqliteEventStore(
            db=file_repo.connection,
            write_lock=file_repo.write_lock,
        )
    return _singletons["event_store"]


def get_user_settings_service() -> UserSettingsService:
    """Get the UserSettingsService singleton, sharing the DB connection from FileRepository."""
    if "user_settings_service" not in _singletons:
        file_repo = get_file_repository()
        _singletons["user_settings_service"] = UserSettingsService(
            db=file_repo.connection,
            write_lock=file_repo.write_lock,
        )
    return _singletons["user_settings_service"]


def reset_singletons() -> None:
    global _singletons
    _singletons.clear()
