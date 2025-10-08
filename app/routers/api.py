from fastapi import APIRouter
from fastapi import Depends
from ..dependencies import get_settings
from ..config import Settings
from ..logging_config import get_app_logger

router = APIRouter()


@router.get("/hello")
async def hello_world():
    """Simple hello world API endpoint"""
    logger = get_app_logger()
    logger.info("Hello world endpoint called", extra={"operation": "api_hello"})
    return {"message": "Hello World from API!"}

@router.get("/settings", response_model=Settings)
async def read_settings(settings: Settings = Depends(get_settings)):
    """Get current application settings"""
    logger = get_app_logger()
    logger.info("Settings endpoint called", extra={"operation": "api_settings"})
    return settings
