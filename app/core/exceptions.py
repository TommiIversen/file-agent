# app/core/exceptions.py

class InvalidTransitionError(Exception):
    """Raised when a file status transition is not allowed."""
    def __init__(self, file_path: str, from_status: str, to_status: str):
        self.file_path = file_path
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            f"Invalid state transition for {file_path}: "
            f"Cannot move from '{from_status}' to '{to_status}'."
        )