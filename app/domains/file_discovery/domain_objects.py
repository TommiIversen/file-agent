"""
File Discovery Domain Configuration Objects
Configuration objects used by file discovery operations.
"""
from dataclasses import dataclass


@dataclass
class ScanConfiguration:
    """Configuration object for file scanning operations."""

    source_directory: str
    polling_interval_seconds: int
    file_stable_time_seconds: int
    keep_files_hours: int  # Applies to ALL file types, not just completed

    # Growing file settings
    growing_file_poll_interval_seconds: int = 5
    growing_file_safety_margin_mb: int = 50
    growing_file_growth_timeout_seconds: int = 300
    growing_file_chunk_size_kb: int = 2048