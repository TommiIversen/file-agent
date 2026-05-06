from typing import Any

from app.domains.system_metrics.metrics_timeseries import MetricsTimeSeries
from app.domains.system_metrics.queries import GetPerformanceHistoryQuery


class GetPerformanceHistoryQueryHandler:
    """Returns the full metrics time-series ring buffer."""

    def __init__(self, timeseries: MetricsTimeSeries) -> None:
        self._timeseries = timeseries

    async def handle(self, query: GetPerformanceHistoryQuery) -> list[dict[str, Any]]:
        return self._timeseries.all()
