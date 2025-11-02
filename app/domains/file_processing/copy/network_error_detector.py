import errno
import asyncio
from typing import Optional

from app.core.events.event_bus import DomainEventBus
from app.core.events.storage_events import NetworkFailureDetectedEvent


class NetworkError(Exception):
    """Custom exception for network-related errors in copy operations."""
    pass


class NetworkErrorDetector:
    """
    Detects network errors early during copy operations for fail-fast behavior.
    Nu med event publishing for NetworkCoordinator integration! 🚀
    """

    # Network error indicators to check for
    NETWORK_ERROR_STRINGS = {
        "input/output error",
        "errno 5",
        "connection refused",
        "network is unreachable",
        "no route to host",
        "connection timed out",
        "broken pipe",
        "errno 32",
        "errno 110",
        "errno 111",
        "smb error",
        "cifs error",
        "mount_smbfs",
        "network mount",
        "permission denied",
        "invalid argument",
        "errno 22",
        "network path was not found",
        "winerror 53",
        "the network name cannot be found",
        "winerror 67",
        "the network location cannot be reached",
        "winerror 1231",
        "access is denied",
        "errno 13",
    }

    # Network-related errno codes (including Windows-specific)
    NETWORK_ERRNO_CODES = {
        errno.EIO,
        errno.ECONNREFUSED,
        errno.ETIMEDOUT,
        errno.ENETUNREACH,
        errno.EHOSTUNREACH,
        errno.EPIPE,
        errno.EACCES,
        errno.ENOTCONN,
        errno.ECONNRESET,
        errno.EINVAL,  # Can be network-related on Windows when destination unavailable
        errno.ENOENT,  # Network path not found
        errno.EACCES,  # Access denied (can be network mount issues)
        53,
        67,
        1231,  # Windows-specific network error codes
    }

    def __init__(self, event_bus: Optional[DomainEventBus] = None, current_file_id: Optional[str] = None):
        """
        Initialiserer den reaktive netværksfejl-detektor.
        
        Args:
            event_bus: EventBus for at publicere NetworkFailureDetectedEvent
            current_file_id: ID på filen der kopieres (til event context)
        """
        self._event_bus = event_bus
        self._current_file_id = current_file_id

    def _is_network_error_string(self, error_str: str) -> bool:
        return any(indicator in error_str for indicator in self.NETWORK_ERROR_STRINGS)

    def _is_network_errno(self, error: Exception) -> bool:
        return hasattr(error, "errno") and error.errno in self.NETWORK_ERRNO_CODES

    def check_write_error(self, error: Exception, operation: str = "write") -> None:
        """
        Checker for netværksfejl og publicerer event før exception rejses.
        
        Args:
            error: Exception der skal tjekkes
            operation: Beskrivelse af operationen (f.eks. "growing copy chunk write")
        """
        error_str = str(error).lower()

        if self._is_network_error_string(error_str) or self._is_network_errno(error):
            # 🚀 PUBLICER EVENT FØR EXCEPTION!
            if self._event_bus and self._current_file_id:
                event = NetworkFailureDetectedEvent(
                    error_message=str(error),
                    file_id=self._current_file_id,
                    operation=operation
                )
                # Fire-and-forget event publishing
                asyncio.create_task(self._event_bus.publish(event))
                
            raise NetworkError(f"Network error during {operation}: {error}")
