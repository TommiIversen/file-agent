"""
Background service that periodically collects system metrics,
records them in a ring buffer, publishes events for live UI,
and logs a summary to the log file every 30 seconds.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.events.event_bus import DomainEventBus
from app.core.events.system_metrics_events import SystemMetricsUpdatedEvent
from app.domains.system_metrics.metrics_collector import collect_system_metrics
from app.domains.system_metrics.metrics_timeseries import MetricsTimeSeries

logger = logging.getLogger(__name__)

# Collection every 10s, log every 30s (every 3rd sample)
_COLLECT_INTERVAL_SECONDS = 10
_LOG_EVERY_N_SAMPLES = 3


class MetricsService:
    """Background service for system metrics collection and broadcast."""

    def __init__(self, event_bus: DomainEventBus) -> None:
        self._event_bus = event_bus
        self._timeseries = MetricsTimeSeries(max_samples=60)
        self._task: asyncio.Task | None = None  # type: ignore[type-arg]
        self._sample_count = 0

    @property
    def timeseries(self) -> MetricsTimeSeries:
        return self._timeseries

    async def start_monitoring(self) -> asyncio.Task:  # type: ignore[type-arg]
        """Start the background metrics collection loop. Returns the task."""
        self._task = asyncio.create_task(self._collection_loop())
        logger.info("MetricsService started (interval=%ds)", _COLLECT_INTERVAL_SECONDS)
        return self._task

    async def stop(self) -> None:
        """Cancel the background task."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("MetricsService stopped")

    async def _collection_loop(self) -> None:
        # Prime psutil cpu_percent (first call always returns 0.0)
        collect_system_metrics()
        await asyncio.sleep(_COLLECT_INTERVAL_SECONDS)

        while True:
            try:
                snapshot = await asyncio.to_thread(collect_system_metrics)
                sample = self._timeseries.record(snapshot)
                self._sample_count += 1

                # Publish event for live WebSocket broadcast
                await self._event_bus.publish(
                    SystemMetricsUpdatedEvent(sample=sample)
                )

                # Log every 30s (every 3rd sample)
                if self._sample_count % _LOG_EVERY_N_SAMPLES == 0:
                    logger.info(
                        "System metrics: CPU=%.1f%% MEM=%.1f%% DISK=%.1f%% "
                        "NET ↓%.1f ↑%.1f Mbps",
                        snapshot.cpu_percent,
                        snapshot.memory_percent,
                        snapshot.disk_percent,
                        snapshot.net_rx_mbps,
                        snapshot.net_tx_mbps,
                    )

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error collecting system metrics")

            await asyncio.sleep(_COLLECT_INTERVAL_SECONDS)
