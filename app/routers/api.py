import logging

from fastapi import APIRouter
from fastapi import Depends

from ..config import Settings
from ..dependencies import get_settings

router = APIRouter()


@router.get("/settings", response_model=Settings)
async def read_settings(settings: Settings = Depends(get_settings)):
    """Get current application settings"""

    logging.info("Settings endpoint called", extra={"operation": "api_settings"})
    return settings
