"""
Audio Recording API Endpoints

REST endpoints for audio device listing, recording status,
and manual test recording (start/stop from settings UI).
Settings CRUD is handled by the existing /api/system/user-settings endpoint.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from app.core.cqrs.command_bus import CommandBus
from app.core.cqrs.query_bus import QueryBus
from app.dependencies.core import get_command_bus, get_query_bus

from .commands import StartAudioRecordingCommand, StopAudioRecordingCommand
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


@router.post("/test/start", response_model=Dict[str, Any])
async def test_start_recording(
    command_bus: CommandBus = Depends(get_command_bus),
) -> Dict[str, Any]:
    """Start a test recording from the settings UI (bypasses Justin)."""
    stem = datetime.now().strftime("%y%m%d_%H%M%S_TEST")
    session_id = f"test-{uuid.uuid4().hex[:8]}"
    result = await command_bus.execute(
        StartAudioRecordingCommand(
            filename_stem=stem,
            channel_name=None,
            session_id=session_id,
        )
    )
    return result


@router.post("/test/stop", response_model=Dict[str, Any])
async def test_stop_recording(
    command_bus: CommandBus = Depends(get_command_bus),
) -> Dict[str, Any]:
    """Stop the current test recording."""
    result = await command_bus.execute(StopAudioRecordingCommand())
    return result
