"""
Progress calculation utilities for File Transfer Agent.

Pure functions for copy progress calculation, update decisions, and formatting.
These functions have no side effects and are easily testable.

Part of Fase 1.2 refactoring: Extract Pure Functions from FileCopyService.
"""

from typing import Dict, Any, Tuple


def calculate_copy_progress(bytes_copied: int, total_bytes: int) -> float:
    """
    Calculate copy progress as percentage.

    Pure function that calculates progress with proper handling of edge cases.

    Args:
        bytes_copied: Number of bytes copied so far
        total_bytes: Total number of bytes to copy

    Returns:
        Progress as percentage (0.0 to 100.0)

    Examples:
        >>> calculate_copy_progress(0, 1000)
        0.0
        >>> calculate_copy_progress(500, 1000)
        50.0
        >>> calculate_copy_progress(1000, 1000)
        100.0
        >>> calculate_copy_progress(0, 0)  # Edge case: empty file
        100.0
    """
    if total_bytes == 0:
        return 100.0  # Empty file is "complete"

    if bytes_copied >= total_bytes:
        return 100.0

    if bytes_copied <= 0:
        return 0.0

    return (bytes_copied / total_bytes) * 100.0


def calculate_progress_percent_int(bytes_copied: int, total_bytes: int) -> int:
    """
    Calculate copy progress as whole number percentage.

    Similar to calculate_copy_progress but returns integer for interval checking.

    Args:
        bytes_copied: Number of bytes copied so far
        total_bytes: Total number of bytes to copy

    Returns:
        Progress as integer percentage (0 to 100)

    Examples:
        >>> calculate_progress_percent_int(500, 1000)
        50
        >>> calculate_progress_percent_int(333, 1000)
        33
    """
    return int(calculate_copy_progress(bytes_copied, total_bytes))


def should_report_progress(
    current_percent: int,
    last_reported_percent: int,
    update_interval: int,
    is_complete: bool = False,
) -> bool:
    """
    Determine if progress should be reported based on interval and completion.

    Pure function that decides when to send progress updates to avoid spam.

    Args:
        current_percent: Current progress percentage (0-100)
        last_reported_percent: Last reported progress percentage
        update_interval: Report interval (e.g., 5 = every 5%)
        is_complete: Whether the operation is complete (always report)

    Returns:
        True if progress should be reported

    Examples:
        >>> should_report_progress(5, -1, 5)  # First update at 5%
        True
        >>> should_report_progress(7, 5, 5)   # 7% - not at interval
        False
        >>> should_report_progress(10, 5, 5)  # 10% - at interval
        True
        >>> should_report_progress(99, 95, 5, is_complete=True)  # Always report completion
        True
    """
    # Always report completion
    if is_complete:
        return True

    # Report if we haven't reported anything yet
    if last_reported_percent < 0:
        return current_percent >= update_interval

    # Report if current progress has crossed an interval boundary
    if current_percent != last_reported_percent:
        return current_percent % update_interval == 0

    return False


def should_report_progress_with_bytes(
    bytes_copied: int,
    total_bytes: int,
    last_reported_percent: int,
    update_interval: int,
) -> Tuple[bool, int]:
    """
    Combined function that calculates progress and determines if it should be reported.

    Convenience function that combines progress calculation and reporting decision.

    Args:
        bytes_copied: Number of bytes copied so far
        total_bytes: Total number of bytes to copy
        last_reported_percent: Last reported progress percentage
        update_interval: Report interval (e.g., 5 = every 5%)

    Returns:
        Tuple of (should_report, current_percent)

    Examples:
        >>> should_report_progress_with_bytes(500, 1000, -1, 5)
        (True, 50)  # 50% reached, should report
        >>> should_report_progress_with_bytes(520, 1000, 50, 5)
        (False, 52)  # 52% - not at interval boundary
    """
    current_percent = calculate_progress_percent_int(bytes_copied, total_bytes)
    is_complete = bytes_copied >= total_bytes

    should_report = should_report_progress(
        current_percent, last_reported_percent, update_interval, is_complete
    )

    return should_report, current_percent


def format_progress_info(
    percent: float, bytes_copied: int, total_bytes: int
) -> Dict[str, Any]:
    """
    Format progress information for logging or UI display.

    Pure function that creates structured progress information.

    Args:
        percent: Progress percentage (0.0 to 100.0)
        bytes_copied: Number of bytes copied so far
        total_bytes: Total number of bytes to copy

    Returns:
        Dictionary with formatted progress information

    Examples:
        >>> info = format_progress_info(50.0, 512000, 1024000)
        >>> info['percent']
        50.0
        >>> info['bytes_copied_mb']
        0.49
    """
    return {
        "percent": round(percent, 1),
        "bytes_copied": bytes_copied,
        "total_bytes": total_bytes,
        "bytes_remaining": max(0, total_bytes - bytes_copied),
        "bytes_copied_kb": round(bytes_copied / 1024, 1),
        "total_bytes_kb": round(total_bytes / 1024, 1),
        "bytes_copied_mb": round(bytes_copied / (1024 * 1024), 2),
        "total_bytes_mb": round(total_bytes / (1024 * 1024), 2),
        "is_complete": bytes_copied >= total_bytes,
        "progress_bar": create_simple_progress_bar(percent),
    }


def create_simple_progress_bar(percent: float, width: int = 20) -> str:
    """
    Create a simple text-based progress bar.

    Pure function for creating visual progress representation.

    Args:
        percent: Progress percentage (0.0 to 100.0)
        width: Width of the progress bar in characters

    Returns:
        Text-based progress bar string

    Examples:
        >>> create_simple_progress_bar(50.0, 10)
        '[#####     ]'
        >>> create_simple_progress_bar(100.0, 10)
        '[##########]'
        >>> create_simple_progress_bar(0.0, 10)
        '[          ]'
    """
    if percent < 0:
        percent = 0.0
    elif percent > 100:
        percent = 100.0

    filled = int((percent / 100.0) * width)
    empty = width - filled

    return f"[{'#' * filled}{' ' * empty}]"


def format_bytes_human_readable(bytes_value: int) -> str:
    """
    Format bytes in human-readable format (KB, MB, GB).

    Pure function for displaying file sizes in user-friendly format.

    Args:
        bytes_value: Number of bytes to format

    Returns:
        Human-readable string representation

    Examples:
        >>> format_bytes_human_readable(1024)
        '1.0 KB'
        >>> format_bytes_human_readable(1536)
        '1.5 KB'
        >>> format_bytes_human_readable(1048576)
        '1.0 MB'
        >>> format_bytes_human_readable(512)
        '512 B'
    """
    if bytes_value < 1024:
        return f"{bytes_value} B"
    elif bytes_value < 1024 * 1024:
        kb = bytes_value / 1024
        return f"{kb:.1f} KB"
    elif bytes_value < 1024 * 1024 * 1024:
        mb = bytes_value / (1024 * 1024)
        return f"{mb:.1f} MB"
    else:
        gb = bytes_value / (1024 * 1024 * 1024)
        return f"{gb:.1f} GB"


def calculate_transfer_rate(bytes_copied: int, elapsed_seconds: float) -> float:
    """
    Calculate transfer rate in bytes per second.

    Pure function for calculating copy speed.

    Args:
        bytes_copied: Number of bytes copied
        elapsed_seconds: Time elapsed in seconds

    Returns:
        Transfer rate in bytes per second

    Examples:
        >>> calculate_transfer_rate(1024, 1.0)
        1024.0
        >>> calculate_transfer_rate(0, 5.0)
        0.0
        >>> calculate_transfer_rate(1024, 0.0)  # Edge case
        0.0
    """
    if elapsed_seconds <= 0:
        return 0.0

    return bytes_copied / elapsed_seconds


def format_transfer_rate_human_readable(rate_bytes_per_sec: float) -> str:
    """
    Format transfer rate in human-readable format.

    Pure function for displaying transfer speeds.

    Args:
        rate_bytes_per_sec: Transfer rate in bytes per second

    Returns:
        Human-readable rate string

    Examples:
        >>> format_transfer_rate_human_readable(1024.0)
        '1.0 KB/s'
        >>> format_transfer_rate_human_readable(1536.0)
        '1.5 KB/s'
        >>> format_transfer_rate_human_readable(1048576.0)
        '1.0 MB/s'
    """
    return f"{format_bytes_human_readable(int(rate_bytes_per_sec))}/s"


def estimate_time_remaining(
    bytes_copied: int, total_bytes: int, rate_bytes_per_sec: float
) -> float:
    """
    Estimate remaining time based on current transfer rate.

    Pure function for predicting completion time.

    Args:
        bytes_copied: Number of bytes copied so far
        total_bytes: Total number of bytes to copy
        rate_bytes_per_sec: Current transfer rate in bytes per second

    Returns:
        Estimated remaining time in seconds (0.0 if complete or no rate)

    Examples:
        >>> estimate_time_remaining(500, 1000, 100.0)
        5.0
        >>> estimate_time_remaining(1000, 1000, 100.0)  # Complete
        0.0
        >>> estimate_time_remaining(500, 1000, 0.0)  # No rate
        0.0
    """
    if bytes_copied >= total_bytes:
        return 0.0  # Already complete

    if rate_bytes_per_sec <= 0:
        return 0.0  # No rate or invalid rate

    bytes_remaining = total_bytes - bytes_copied
    return bytes_remaining / rate_bytes_per_sec
