"""
Network Mount Module - SRP Compliant Implementation

This module contains the network mount system that adheres to
Single Responsibility Principle and size mandates (<250 lines per class).

Components:
- NetworkMountService: Main orchestrator (<200 lines)
- BaseMounter: Abstract base class for platform operations (<50 lines)
- MacOSMounter: macOS mount implementation with robust validation (<200 lines)
- WindowsMounter: Windows mount implementation (<150 lines)
- PlatformFactory: Platform detection and factory (<50 lines)
- MacOSMountUtils: Utilities for macOS mount validation and cleanup (<300 lines)

Each class has a single, well-defined responsibility following SRP mandate.
This module enables automatic network drive mounting and reconnection with
robust validation to prevent dangerous local folder creation at mount points.
"""

from .base_mounter import BaseMounter
from .mount_config import MountConfigHandler
from .mount_service import NetworkMountService
from .platform_factory import PlatformFactory

__all__ = [
    "NetworkMountService",
    "BaseMounter",
    "PlatformFactory",
    "MountConfigHandler",
]
