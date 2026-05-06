import logging

from app.core.cqrs.query_bus import QueryBus
from app.domains.system_metrics.metrics_service import MetricsService
from app.domains.system_metrics.queries import GetPerformanceHistoryQuery
from app.domains.system_metrics.query_handlers import GetPerformanceHistoryQueryHandler


def register_system_metrics_domain(query_bus: QueryBus, metrics_service: MetricsService) -> None:
    """Register system_metrics CQRS handlers."""
    logging.info("Registrerer 'System Metrics' CQRS handlers...")

    handler = GetPerformanceHistoryQueryHandler(metrics_service.timeseries)
    query_bus.register(GetPerformanceHistoryQuery, handler.handle)

    logging.info("System Metrics domain-registrering fuldført.")
