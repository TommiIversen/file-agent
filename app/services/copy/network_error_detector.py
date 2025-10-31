import errno


class NetworkError(Exception):
    """Custom exception for network-related errors in copy operations."""

    pass


class NetworkErrorDetector:
    """Detects network errors early during copy operations for fail-fast behavior."""

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

    def __init__(self):
     """
        Initialiserer den reaktive netværksfejl-detektor.
        Denne klasse analyserer kun fejl, efter de er sket.
        """
    pass

    def _is_network_error_string(self, error_str: str) -> bool:
        return any(indicator in error_str for indicator in self.NETWORK_ERROR_STRINGS)

    def _is_network_errno(self, error: Exception) -> bool:
        return hasattr(error, "errno") and error.errno in self.NETWORK_ERRNO_CODES

    def check_write_error(self, error: Exception, operation: str = "write") -> None:
        error_str = str(error).lower()

        if self._is_network_error_string(error_str) or self._is_network_errno(error):
            raise NetworkError(f"Network error during {operation}: {error}")
