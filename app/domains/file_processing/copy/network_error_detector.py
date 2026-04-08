import errno
import asyncio
import re
import logging
from typing import Optional

from app.core.events.event_bus import DomainEventBus
from app.core.events.storage_events import NetworkFailureDetectedEvent


class NetworkError(Exception):
    """Custom exception for network-related errors in copy operations."""
    pass


class NetworkErrorDetector:
    """
    Detects network errors early during copy operations for fail-fast behavior.
    Nu med event publishing for NetworkCoordinator integration! 
    """

    # Plain substring patterns (no word-boundary needed)
    _PLAIN_PATTERNS: list[str] = [
        "input/output error",
        "bad file descriptor",
        "connection refused",
        "network is unreachable",
        "no route to host",
        "connection timed out",
        "broken pipe",
        "smb error",
        "cifs error",
        "mount_smbfs",
        "network mount",
        "permission denied",
        "invalid argument",
        "network path was not found",
        "the network name cannot be found",
        "the network location cannot be reached",
        "access is denied",
    ]

    # Numeric error code patterns that need word-boundary matching
    _CODE_PATTERNS: list[str] = [
        r"errno 5\b",
        r"errno 9\b",
        r"errno 13\b",
        r"errno 22\b",
        r"errno 32\b",
        r"errno 110\b",
        r"errno 111\b",
        r"winerror 53\b",
        r"winerror 67\b",
        r"winerror 1231\b",
    ]

    _NETWORK_ERROR_PATTERN: re.Pattern[str] = re.compile(
        "|".join(
            [re.escape(p) for p in _PLAIN_PATTERNS] + _CODE_PATTERNS
        )
    )

    # Network-related errno codes (including Windows-specific)
    NETWORK_ERRNO_CODES: set[int] = {
        errno.EIO,
        errno.EBADF,
        errno.ECONNREFUSED,
        errno.ETIMEDOUT,
        errno.ENETUNREACH,
        errno.EHOSTUNREACH,
        errno.EPIPE,
        errno.EACCES,
        errno.ENOTCONN,
        errno.ECONNRESET,
        errno.EINVAL,
        errno.ENOENT,
        53,
        67,
        1231,
    }

    def __init__(self, event_bus: Optional[DomainEventBus] = None, current_file_id: Optional[str] = None):
        self._event_bus = event_bus
        self._current_file_id = current_file_id
        self._pending_tasks: set[asyncio.Task[None]] = set()

    def _is_network_error_string(self, error_str: str) -> bool:
        return bool(self._NETWORK_ERROR_PATTERN.search(error_str))

    def _is_network_errno(self, error: Exception) -> bool:
        return hasattr(error, "errno") and error.errno in self.NETWORK_ERRNO_CODES

    def check_write_error(self, error: Exception, operation: str = "write") -> None:
        error_str = str(error).lower()

        if self._is_network_error_string(error_str) or self._is_network_errno(error):
            self._publish_failure_event(error, operation)
            raise NetworkError(f"Network error during {operation}: {error}") from error

    def _publish_failure_event(self, error: Exception, operation: str) -> None:
        if not (self._event_bus and self._current_file_id):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logging.warning(
                "No running event loop — skipping NetworkFailureDetectedEvent for file %s. Error: %s",
                self._current_file_id,
                str(error),
            )
            return
        event = NetworkFailureDetectedEvent(
            error_message=str(error),
            file_id=self._current_file_id,
            operation=operation,
        )
        task = loop.create_task(self._event_bus.publish(event))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)
