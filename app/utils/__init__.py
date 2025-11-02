"""
Utilities package for File Transfer Agent.

This package contains pure functions and utilities that support
the main application logic without side effects.
"""

from .file_operations import (
    calculate_relative_path,
    generate_conflict_free_path,
    build_destination_path,
)

from .progress_utils import (
    format_bytes_human_readable,
    calculate_transfer_rate,
    format_transfer_rate_human_readable,
    estimate_time_remaining,
)

__all__ = [
    # File operations
    "calculate_relative_path",
    "generate_conflict_free_path",
    "build_destination_path",
    # Progress utilities
    "format_bytes_human_readable",
    "calculate_transfer_rate",
    "format_transfer_rate_human_readable",
    "estimate_time_remaining",
]
