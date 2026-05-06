from fastapi import APIRouter

from app.dependencies.core import get_query_bus
from app.domains.system_metrics.queries import GetPerformanceHistoryQuery

router = APIRouter(prefix="/api/system-metrics", tags=["system-metrics"])


@router.get("/history")
async def get_performance_history():
    """Return the last ~10 minutes of system metrics (ring buffer)."""
    query_bus = get_query_bus()
    history = await query_bus.execute(GetPerformanceHistoryQuery())
    return {"history": history}
