"""
Scanner API endpoints for the File Discovery domain.

These endpoints handle file scanner control operations using CQRS patterns.
"""
from fastapi import APIRouter, Depends
from app.core.cqrs.command_bus import CommandBus
from app.dependencies.core import get_command_bus
from ..commands import PauseScannerCommand, ResumeScannerCommand

router = APIRouter(prefix="/api/scanner", tags=["File Scanner"])


@router.post("/pause")
async def pause_file_scanner(command_bus: CommandBus = Depends(get_command_bus)):
    """Pause the file scanner (stop polling for new jobs) via CQRS Command."""
    return await command_bus.execute(PauseScannerCommand())


@router.post("/resume")
async def resume_file_scanner(command_bus: CommandBus = Depends(get_command_bus)):
    """Resume the file scanner (start polling for new jobs) via CQRS Command."""
    return await command_bus.execute(ResumeScannerCommand())