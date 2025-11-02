



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
