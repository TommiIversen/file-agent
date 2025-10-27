"""Progress calculation utilities for File Transfer Agent."""

from typing import Dict, Any, Tuple


def calculate_copy_progress(bytes_copied: int, total_bytes: int) -> float:
    if total_bytes == 0:
        return 100.0  # Empty file is "complete"

    if bytes_copied >= total_bytes:
        return 100.0

    if bytes_copied <= 0:
        return 0.0

    return (bytes_copied / total_bytes) * 100.0


def calculate_progress_percent_int(bytes_copied: int, total_bytes: int) -> int:
    return int(calculate_copy_progress(bytes_copied, total_bytes))


def should_report_progress(
    current_percent: int,
    last_reported_percent: int,
    update_interval: int,
    is_complete: bool = False,
) -> bool:
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
    current_percent = calculate_progress_percent_int(bytes_copied, total_bytes)
    is_complete = bytes_copied >= total_bytes

    should_report = should_report_progress(
        current_percent, last_reported_percent, update_interval, is_complete
    )

    return should_report, current_percent


def format_progress_info(
    percent: float, bytes_copied: int, total_bytes: int
) -> Dict[str, Any]:
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
    if percent < 0:
        percent = 0.0
    elif percent > 100:
        percent = 100.0

    filled = int((percent / 100.0) * width)
    empty = width - filled

    return f"[{'#' * filled}{' ' * empty}]"


def format_bytes_human_readable(bytes_value: int) -> str:
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
    if elapsed_seconds <= 0:
        return 0.0

    return bytes_copied / elapsed_seconds


def format_transfer_rate_human_readable(rate_bytes_per_sec: float) -> str:
    return f"{format_bytes_human_readable(int(rate_bytes_per_sec))}/s"


def estimate_time_remaining(
    bytes_copied: int, total_bytes: int, rate_bytes_per_sec: float
) -> float:
    if bytes_copied >= total_bytes:
        return 0.0  # Already complete

    if rate_bytes_per_sec <= 0:
        return 0.0  # No rate or invalid rate

    bytes_remaining = total_bytes - bytes_copied
    return bytes_remaining / rate_bytes_per_sec
