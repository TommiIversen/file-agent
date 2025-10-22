from fastapi import APIRouter, Depends

from app.dependencies import get_job_queue_service
from app.services.job_queue import JobQueueService

router = APIRouter(prefix="/api/state", tags=["state"])

