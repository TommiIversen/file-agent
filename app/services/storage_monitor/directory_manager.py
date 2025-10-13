"""
Directory Management for File Transfer Agent.

This class is responsible solely for directory lifecycle operations,
adhering to SRP.
"""

from pathlib import Path

from ...logging_config import get_app_logger


class DirectoryManager:
    """
    Manages directory creation and lifecycle operations.
    
    Single Responsibility: Directory operations ONLY
    Size: <150 lines (currently ~60 lines)
    
    This class is responsible solely for directory lifecycle management, adhering to SRP.
    """
    
    def __init__(self):
        """Initialize directory manager.""" 
        # This class is responsible solely for directory lifecycle management, adhering to SRP
        self._logger = get_app_logger()
        
    async def ensure_directory_exists(self, path: str, storage_type: str) -> bool:
        """
        Central directory recreation logic - the single authority for directory lifecycle.
        
        This method eliminates Shotgun Surgery by consolidating ALL directory creation
        logic into DirectoryManager, adhering to SRP mandate.
        
        Args:
            path: Directory path to ensure exists
            storage_type: "source" or "destination" for logging context
            
        Returns:
            True if directory exists or was successfully created
        """
        try:
            path_obj = Path(path)
            
            if path_obj.exists() and path_obj.is_dir():
                return True
                
            self._logger.info(f"Creating missing {storage_type} directory: {path}")
            path_obj.mkdir(parents=True, exist_ok=True)
            
            # Verify creation was successful
            if path_obj.exists() and path_obj.is_dir():
                self._logger.info(f"Successfully created {storage_type} directory: {path}")
                return True
            else:
                self._logger.error(f"Directory creation appeared successful but verification failed: {path}")
                return False
                
        except Exception as e:
            self._logger.error(f"Failed to create {storage_type} directory {path}: {e}")
            return False