"""
API endpoints for testing og debugging af StateManager og FileScannerService.

Grundlæggende endpoints til at inspicere systemets tilstand
og manuelt tilføje filer for testing.
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime

from app.models import TrackedFile, FileStatus
from app.services.state_manager import StateManager
from app.services.file_scanner import FileScannerService
from app.services.job_queue import JobQueueService
from app.services.file_copier import FileCopyService
from app.dependencies import get_state_manager, get_file_scanner, get_job_queue_service, get_file_copier

router = APIRouter(prefix="/api/state", tags=["state"])


@router.get("/files", response_model=List[TrackedFile])
async def get_all_files(
    state_manager: StateManager = Depends(get_state_manager)
) -> List[TrackedFile]:
    """
    Hent alle tracked filer.
    
    Returns:
        Liste af alle TrackedFile objekter
    """
    return await state_manager.get_all_files()


@router.get("/files/{status}", response_model=List[TrackedFile])
async def get_files_by_status(
    status: FileStatus,
    state_manager: StateManager = Depends(get_state_manager)
) -> List[TrackedFile]:
    """
    Hent alle filer med en specifik status.
    
    Args:
        status: Den ønskede FileStatus
        
    Returns:
        Liste af TrackedFile objekter med den givne status
    """
    return await state_manager.get_files_by_status(status)


@router.get("/statistics")
async def get_statistics(
    state_manager: StateManager = Depends(get_state_manager)
) -> dict:
    """
    Hent statistik om systemets tilstand.
    
    Returns:
        Dictionary med forskellige statistikker
    """
    return await state_manager.get_statistics()


@router.post("/files/add")
async def add_test_file(
    file_path: str,
    file_size: int = 1024,
    state_manager: StateManager = Depends(get_state_manager)
) -> TrackedFile:
    """
    Tilføj en test fil til StateManager (kun til testing/debugging).
    
    Args:
        file_path: Sti til filen
        file_size: Filstørrelse i bytes
        
    Returns:
        Det oprettede TrackedFile objekt
    """
    return await state_manager.add_file(
        file_path=file_path,
        file_size=file_size,
        last_write_time=datetime.now()
    )


@router.put("/files/{file_path:path}/status")
async def update_file_status(
    file_path: str,
    status: FileStatus,
    state_manager: StateManager = Depends(get_state_manager)
) -> TrackedFile:
    """
    Opdater status for en specifik fil (kun til testing/debugging).
    
    Args:
        file_path: Sti til filen
        status: Ny status
        
    Returns:
        Det opdaterede TrackedFile objekt
        
    Raises:
        HTTPException: Hvis filen ikke findes
    """
    updated_file = await state_manager.update_file_status(file_path, status)
    
    if updated_file is None:
        raise HTTPException(status_code=404, detail=f"Fil ikke fundet: {file_path}")
    
    return updated_file


@router.delete("/files/{file_path:path}")
async def remove_file(
    file_path: str,
    state_manager: StateManager = Depends(get_state_manager)
) -> dict:
    """
    Fjern en fil fra StateManager (kun til testing/debugging).
    
    Args:
        file_path: Sti til filen
        
    Returns:
        Dictionary med resultat
        
    Raises:
        HTTPException: Hvis filen ikke findes
    """
    success = await state_manager.remove_file(file_path)
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Fil ikke fundet: {file_path}")
    
    return {"message": f"Fil fjernet: {file_path}"}


@router.get("/scanner/statistics")
async def get_scanner_statistics(
    file_scanner: FileScannerService = Depends(get_file_scanner)
) -> dict:
    """
    Hent statistikker om FileScannerService aktivitet.
    
    Returns:
        Dictionary med scanner statistikker
    """
    return await file_scanner.get_scanning_statistics()


@router.get("/scanner/status")
async def get_scanner_status(
    file_scanner: FileScannerService = Depends(get_file_scanner)
) -> dict:
    """
    Hent status for FileScannerService.
    
    Returns:
        Dictionary med scanner status
    """
    stats = await file_scanner.get_scanning_statistics()
    return {
        "is_running": stats["is_running"],
        "source_path": stats["source_path"],
        "files_being_tracked": stats["files_being_tracked"]
    }


@router.get("/queue/statistics")
async def get_queue_statistics(
    job_queue_service: JobQueueService = Depends(get_job_queue_service)
) -> dict:
    """
    Hent statistikker om JobQueueService.
    
    Returns:
        Dictionary med queue statistikker
    """
    return await job_queue_service.get_queue_statistics()


@router.get("/queue/status")
async def get_queue_status(
    job_queue_service: JobQueueService = Depends(get_job_queue_service)
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
        "is_empty": stats["is_empty"]
    }


@router.get("/queue/failed-jobs")
async def get_failed_jobs(
    job_queue_service: JobQueueService = Depends(get_job_queue_service)
) -> dict:
    """
    Hent failed jobs fra queue.
    
    Returns:
        Dictionary med failed jobs liste
    """
    failed_jobs = await job_queue_service.get_failed_jobs()
    return {
        "failed_jobs": failed_jobs,
        "count": len(failed_jobs)
    }


@router.delete("/queue/failed-jobs")
async def clear_failed_jobs(
    job_queue_service: JobQueueService = Depends(get_job_queue_service)
) -> dict:
    """
    Ryd failed jobs liste.
    
    Returns:
        Dictionary med antal cleared jobs
    """
    count = await job_queue_service.clear_failed_jobs()
    return {"cleared_count": count, "message": f"Cleared {count} failed jobs"}


@router.get("/copier/statistics")
async def get_copier_statistics(
    file_copier: FileCopyService = Depends(get_file_copier)
) -> dict:
    """
    Hent statistikker om FileCopyService aktivitet.
    
    Returns:
        Dictionary med copier statistikker
    """
    return await file_copier.get_copy_statistics()


@router.get("/copier/status")
async def get_copier_status(
    file_copier: FileCopyService = Depends(get_file_copier)
) -> dict:
    """
    Hent status for FileCopyService.
    
    Returns:
        Dictionary med copier status
    """
    stats = await file_copier.get_copy_statistics()
    consumer_status = file_copier.get_consumer_status()
    return {
        "is_running": consumer_status["is_running"],
        "destination_available": consumer_status["destination_available"],
        "total_files_copied": stats["total_files_copied"],
        "total_files_failed": stats["total_files_failed"],
        "total_gb_copied": stats["total_gb_copied"]
    }