"""
Storage & network factories.

StorageChecker, StorageMonitor, NetworkMountService, NetworkCoordinator.
"""
from app.dependencies.core import _singletons, get_settings, get_event_bus
from app.domains.storage.storage_checker import StorageChecker
from app.domains.storage.storage_monitor import StorageMonitorService
from app.domains.network_mount.mount_service import NetworkMountService


def get_storage_checker() -> StorageChecker:
    if "storage_checker" not in _singletons:
        settings = get_settings()
        _singletons["storage_checker"] = StorageChecker(
            test_file_prefix=settings.storage_test_file_prefix,
            io_timeout=settings.storage_io_timeout_seconds,
            network_io_timeout=settings.storage_io_timeout_network_seconds,
        )
    return _singletons["storage_checker"]


def get_network_mount_service() -> NetworkMountService:
    if "network_mount_service" not in _singletons:
        settings = get_settings()
        _singletons["network_mount_service"] = NetworkMountService(settings)
    return _singletons["network_mount_service"]


def get_network_coordinator():
    """
    Get NetworkCoordinator - Single Source of Truth for network status!

    Returns the NetworkCoordinator instance that was created during
    network_mount domain registration.
    """
    if "network_coordinator" not in _singletons:
        raise RuntimeError(
            "NetworkCoordinator not initialized! Ensure register_network_mount_domain() was called."
        )
    return _singletons["network_coordinator"]


def register_network_coordinator(coordinator) -> None:
    """Register the NetworkCoordinator singleton after domain registration."""
    _singletons["network_coordinator"] = coordinator


def get_storage_monitor() -> StorageMonitorService:
    if "storage_monitor" not in _singletons:
        _singletons["storage_monitor"] = StorageMonitorService(
            settings=get_settings(),
            storage_checker=get_storage_checker(),
            event_bus=get_event_bus(),
            network_mount_service=get_network_mount_service(),
        )
    return _singletons["storage_monitor"]
