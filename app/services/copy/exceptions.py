class FileCopyError(Exception):
    """Base exception for file copy operation failures."""
    pass

class FileCopyTimeoutError(FileCopyError):
    """Raised when a file operation (e.g., size check) times out."""
    pass

class FileCopyIOError(FileCopyError):
    """Raised for general I/O errors during file copy."""
    pass

class FileCopyIntegrityError(FileCopyError):
    """Raised when file integrity verification fails after copy."""
    pass
