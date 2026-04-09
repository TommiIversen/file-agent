"""
Lifecycle factories.

LifecycleService.
"""
from app.dependencies.core import (
    _singletons,
    get_settings,
    get_command_bus,
)
from app.domains.lifecycle.service import LifecycleService


def get_lifecycle_service() -> LifecycleService:
    """Get the LifecycleService singleton for background file cleanup."""
    if "lifecycle_service" not in _singletons:
        _singletons["lifecycle_service"] = LifecycleService(
            command_bus=get_command_bus(),
            settings=get_settings(),
        )
    return _singletons["lifecycle_service"]
