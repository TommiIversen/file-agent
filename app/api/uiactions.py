import logging
import os
import sys
import asyncio

from fastapi import APIRouter
from fastapi import Depends

from app.config import Settings
from app.dependencies import get_settings
from app.dependencies import get_file_scanner
from app.dependencies import get_websocket_manager

router = APIRouter(prefix="/api", tags=["uiactions"])



@router.get("/settings", response_model=Settings)
async def read_settings(settings: Settings = Depends(get_settings)):
    """Get current application settings"""

    logging.info("Settings endpoint called", extra={"operation": "api_settings"})
    return settings


@router.get("/config-info")
async def get_config_info(settings: Settings = Depends(get_settings)):
    """Get information about which configuration file is being used"""
    
    logging.info("Config info endpoint called", extra={"operation": "api_config_info"})
    return settings.config_file_info


@router.post("/reload-config")
async def reload_config():
    """Reload configuration from file"""
    
    try:
        logging.info("Config reload requested", extra={"operation": "api_reload_config"})
        
        # Clear the settings cache first!
        from ..dependencies import get_settings
        get_settings.cache_clear()
        
        # Import here to avoid circular imports
        from ..config import Settings
        
        # Create new settings instance to reload from file
        new_settings = Settings()
        
        # Log the reload
        config_info = new_settings.config_file_info
        logging.info(f"Configuration reloaded from: {config_info['active_config_file']}")
        
        return {
            "success": True,
            "message": "Configuration reloaded successfully",
            "config_file": config_info['active_config_file'],
            "hostname": config_info['hostname'],
            "timestamp": config_info.get('load_timestamp', 'unknown')
        }
        
    except Exception as e:
        logging.error(f"Failed to reload configuration: {e}")
        return {
            "success": False,
            "message": f"Failed to reload configuration: {str(e)}"
        }


@router.post("/restart-application")
async def restart_application():
    """Restart the entire application (graceful shutdown and restart)"""
    
    try:
        logging.info("Application restart requested", extra={"operation": "api_restart_app"})
        
        # Schedule restart after a short delay to allow response to be sent
        async def delayed_restart():
            await asyncio.sleep(2)  # Give time for response to be sent
            logging.info("Restarting application...")
            
            # Get the current Python executable and original command
            python_executable = sys.executable
            
            # Restart the application using the same module path
            os.execv(python_executable, [python_executable, '-m', 'app.main'])
        
        # Schedule the restart
        asyncio.create_task(delayed_restart())
        
        return {
            "success": True,
            "message": "Application restart initiated - restarting in 2 seconds...",
            "restart_delay_seconds": 2
        }
        
    except Exception as e:
        logging.error(f"Failed to restart application: {e}")
        return {
            "success": False,
            "message": f"Failed to restart application: {str(e)}"
        }


# --- FileScanner Pause/Resume Endpoints ---

@router.post("/scanner/pause")
async def pause_file_scanner(
    scanner=Depends(get_file_scanner),
    ws_manager=Depends(get_websocket_manager)
):
    """Pause the file scanner (stop polling for new jobs)"""
    await scanner.stop_scanning()
    is_scanning = scanner.is_scanning()

    print(" Pause")

    return {"success": True, "paused": True, "scanning": is_scanning}


@router.post("/scanner/resume")
async def resume_file_scanner(
    scanner=Depends(get_file_scanner),
    ws_manager=Depends(get_websocket_manager)
):
    """Resume the file scanner (start polling for new jobs)"""
    await scanner.start_scanning()
    is_scanning = scanner.is_scanning()

    print(" REsume")
    return {"success": True, "paused": False, "scanning": is_scanning}


@router.get("/scanner/status")
async def get_scanner_status(scanner=Depends(get_file_scanner)):
    """Get current scanner status"""
    return {"scanning": scanner.is_scanning(), "paused": not scanner.is_scanning()}
