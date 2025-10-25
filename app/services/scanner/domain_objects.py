from dataclasses import dataclass


@dataclass
class ScanConfiguration:
    """Configuration object to eliminate long parameter lists."""

    source_directory: str
    polling_interval_seconds: int
    file_stable_time_seconds: int
    keep_files_hours: int  # Renamed: now applies to ALL file types, not just completed

    # Add missing growing file settings
    growing_file_poll_interval_seconds: int = 5
    growing_file_safety_margin_mb: int = 50
    growing_file_growth_timeout_seconds: int = 300
    growing_file_chunk_size_kb: int = 2048
