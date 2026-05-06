"""
Time-series ring buffer for system performance metrics.

Stores the last N samples (default 60 = 10 min at 10s interval).
Each sample is a compact dict suitable for JSON serialization to the dashboard.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

from app.domains.system_metrics.metrics_collector import SystemMetricsSnapshot


class MetricsTimeSeries:
    """Ring buffer for system metrics history."""

    def __init__(self, max_samples: int = 60) -> None:
        self._samples: deque[dict[str, Any]] = deque(maxlen=max_samples)

    def record(self, snapshot: SystemMetricsSnapshot) -> dict[str, Any]:
        """Record a new sample and return it (for live broadcast)."""
        sample: dict[str, Any] = {
            "ts": round(time.time(), 1),
            "cpu": round(snapshot.cpu_percent, 1),
            "cores": [round(c, 1) for c in snapshot.cpu_per_core],
            "mem": round(snapshot.memory_percent, 1),
            "disk": round(snapshot.disk_percent, 1),
            "net_rx": round(snapshot.net_rx_mbps, 2),
            "net_tx": round(snapshot.net_tx_mbps, 2),
        }
        self._samples.append(sample)
        return sample

    def all(self) -> list[dict[str, Any]]:
        """Return all samples (oldest first)."""
        return list(self._samples)

    def latest(self) -> dict[str, Any] | None:
        """Return the most recent sample, or None."""
        return self._samples[-1] if self._samples else None
