"""
File discovery factories.

FileDiscoverySlice, FileScannerService.
"""
from app.dependencies.core import (
    _singletons,
    get_settings,
    get_command_bus,
    get_query_bus,
    get_event_bus,
    get_file_repository,
    get_file_state_machine,
)
from app.domains.file_discovery.file_scanner_service import FileScannerService
from app.domains.file_discovery.file_discovery_slice import FileDiscoverySlice


def get_file_discovery_slice() -> FileDiscoverySlice:
    """Get the File Discovery vertical slice."""
    if "file_discovery_slice" not in _singletons:
        _singletons["file_discovery_slice"] = FileDiscoverySlice(
            file_repository=get_file_repository(),
            event_bus=get_event_bus(),
            state_machine=get_file_state_machine(),
            cooldown_minutes=get_settings().space_error_cooldown_minutes,
            query_bus=get_query_bus(),
        )
    return _singletons["file_discovery_slice"]


def get_file_scanner() -> FileScannerService:
    if "file_scanner" not in _singletons:
        _singletons["file_scanner"] = FileScannerService(
            settings=get_settings(),
            command_bus=get_command_bus(),
            query_bus=get_query_bus(),
            event_bus=get_event_bus(),
        )
    return _singletons["file_scanner"]
