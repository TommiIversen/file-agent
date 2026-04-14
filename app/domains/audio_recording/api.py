"""
Audio Recording API Endpoints

REST endpoints for audio device listing and recording status.
Settings CRUD is handled by the existing /api/system/user-settings endpoint.
"""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from app.core.cqrs.query_bus import QueryBus
from app.dependencies.core import get_query_bus

from .queries import GetAudioDevicesQuery, GetAudioRecordingStatusQuery

router = APIRouter(prefix="/api/audio", tags=["Audio Recording"])


@router.get("/devices", response_model=List[Dict[str, Any]])
async def get_audio_devices(
    query_bus: QueryBus = Depends(get_query_bus),
) -> List[Dict[str, Any]]:
    """List available audio input devices for the current platform."""
    return await query_bus.execute(GetAudioDevicesQuery())


@router.get("/status", response_model=Dict[str, Any])
async def get_audio_status(
    query_bus: QueryBus = Depends(get_query_bus),
) -> Dict[str, Any]:
    """Get current audio recording status."""
    return await query_bus.execute(GetAudioRecordingStatusQuery())
