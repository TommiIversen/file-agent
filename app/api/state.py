from fastapi import APIRouter, Depends

from app.services.job_queue import JobQueueService
from app.dependencies import get_job_queue_service

router = APIRouter(prefix="/api/state", tags=["state"])


@router.get("/queue/status")
async def get_queue_status(
    job_queue_service: JobQueueService = Depends(get_job_queue_service),
) -> dict:
    """
    Hent status for JobQueueService.

    Returns:
        Dictionary med queue status
    """
    stats = await job_queue_service.get_queue_statistics()
    return {
        "is_running": stats["is_running"],
        "queue_size": stats["queue_size"],
        "is_empty": stats["is_empty"],
    }


@router.get("/queue/failed-jobs")
async def get_failed_jobs(
    job_queue_service: JobQueueService = Depends(get_job_queue_service),
) -> dict:
    """
    Hent failed jobs fra queue.

    Returns:
        Dictionary med failed jobs liste
    """
    failed_jobs = await job_queue_service.get_failed_jobs()
    return {"failed_jobs": failed_jobs, "count": len(failed_jobs)}


@router.delete("/queue/failed-jobs")
async def clear_failed_jobs(
    job_queue_service: JobQueueService = Depends(get_job_queue_service),
) -> dict:
    """
    Ryd failed jobs liste.

    Returns:
        Dictionary med antal cleared jobs
    """
    count = await job_queue_service.clear_failed_jobs()
    return {"cleared_count": count, "message": f"Cleared {count} failed jobs"}
