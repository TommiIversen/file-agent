"""
Cross-platform system metrics collection via psutil.

Primary target: macOS (Apple Silicon M1/M2/M3).
Secondary target: Windows.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field

import psutil


@dataclass
class SystemMetricsSnapshot:
    """A single point-in-time system metrics reading."""

    cpu_percent: float = 0.0
    cpu_per_core: list[float] = field(default_factory=list)
    memory_percent: float = 0.0
    disk_percent: float = 0.0
    net_rx_mbps: float = 0.0
    net_tx_mbps: float = 0.0


# Module-level state for network delta calculation
_prev_net_bytes_sent: int = 0
_prev_net_bytes_recv: int = 0
_prev_net_time: float = 0.0


def _get_disk_path() -> str:
    """Return the root disk path for the current platform."""
    if sys.platform == "win32":
        return "C:\\"
    return "/"


def _calculate_net_rates() -> tuple[float, float]:
    """Calculate network RX/TX rates in Mbps using delta from previous call."""
    global _prev_net_bytes_sent, _prev_net_bytes_recv, _prev_net_time

    counters = psutil.net_io_counters()
    now = time.time()

    if _prev_net_time == 0.0:
        # First call — no delta yet, just store baseline
        _prev_net_bytes_sent = counters.bytes_sent
        _prev_net_bytes_recv = counters.bytes_recv
        _prev_net_time = now
        return 0.0, 0.0

    elapsed = now - _prev_net_time
    if elapsed <= 0:
        return 0.0, 0.0

    rx_bytes = counters.bytes_recv - _prev_net_bytes_recv
    tx_bytes = counters.bytes_sent - _prev_net_bytes_sent

    # Convert bytes/sec to Mbps (megabits per second)
    rx_mbps = (rx_bytes / elapsed) * 8 / 1_000_000
    tx_mbps = (tx_bytes / elapsed) * 8 / 1_000_000

    _prev_net_bytes_sent = counters.bytes_sent
    _prev_net_bytes_recv = counters.bytes_recv
    _prev_net_time = now

    return round(rx_mbps, 2), round(tx_mbps, 2)


def collect_system_metrics() -> SystemMetricsSnapshot:
    """Collect current system metrics. Non-blocking (interval=None for CPU)."""
    rx_mbps, tx_mbps = _calculate_net_rates()

    return SystemMetricsSnapshot(
        cpu_percent=psutil.cpu_percent(interval=None),
        cpu_per_core=psutil.cpu_percent(percpu=True),
        memory_percent=psutil.virtual_memory().percent,
        disk_percent=psutil.disk_usage(_get_disk_path()).percent,
        net_rx_mbps=rx_mbps,
        net_tx_mbps=tx_mbps,
    )
