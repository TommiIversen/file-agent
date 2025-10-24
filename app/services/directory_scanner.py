"""
Directory Scanner Service - SRP compliant file/folder discovery service.

This service provides async directory scanning with timeout protection
for source and destination paths. Returns structured data for UI display.

Responsibilities:
- Scan directories for files and folders (including hidden)
- Collect metadata (size, creation time, type)
- Handle network timeouts gracefully
- Return structured Pydantic models

Dependencies: Only Settings - no other service dependencies to maintain SRP
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field

import aiofiles.os

from app.config import Settings


class DirectoryItem(BaseModel):
    """Represents a file or directory with metadata."""
    
    name: str = Field(..., description="File or directory name")
    path: str = Field(..., description="Full path to the item")
    is_directory: bool = Field(..., description="True if item is a directory")
    is_hidden: bool = Field(default=False, description="True if item is hidden")
    size_bytes: Optional[int] = Field(None, description="File size in bytes (None for directories)")
    created_time: Optional[datetime] = Field(None, description="Creation time")
    modified_time: Optional[datetime] = Field(None, description="Last modification time")
    
    model_config = {
        "json_encoders": {
            datetime: lambda v: v.isoformat() if v else None
        }
    }


class DirectoryScanResult(BaseModel):
    """Result of a directory scan operation."""
    
    path: str = Field(..., description="Scanned directory path")
    is_accessible: bool = Field(..., description="Whether directory was accessible")
    items: List[DirectoryItem] = Field(default_factory=list, description="Found files and directories")
    total_items: int = Field(default=0, description="Total number of items found")
    total_files: int = Field(default=0, description="Number of files found")
    total_directories: int = Field(default=0, description="Number of directories found")
    scan_duration_seconds: float = Field(default=0.0, description="Time taken to scan")
    error_message: Optional[str] = Field(None, description="Error message if scan failed")
    
    def __init__(self, **data):
        super().__init__(**data)
        # Auto-calculate totals from items
        if self.items:
            self.total_items = len(self.items)
            self.total_files = sum(1 for item in self.items if not item.is_directory)
            self.total_directories = sum(1 for item in self.items if item.is_directory)


class DirectoryScannerService:
    """
    Async directory scanner service with timeout protection.
    
    SRP: Responsible solely for scanning directories and returning structured metadata.
    No dependencies on other services - only uses Settings for configuration.
    """
    
    def __init__(self, settings: Settings):
        self._settings = settings
        self._scan_timeout = 30.0  # 30 second timeout for directory scans
        self._item_timeout = 5.0   # 5 second timeout per item metadata fetch
        self._max_depth = 10       # Maximum recursion depth to prevent infinite loops
        
        logging.info("DirectoryScannerService initialized with SRP compliance")
    
    async def scan_source_directory(self, recursive: bool = True, max_depth: int = 3) -> DirectoryScanResult:
        """Scan the configured source directory."""
        return await self._scan_directory(
            self._settings.source_directory,
            description="source",
            recursive=recursive,
            max_depth=max_depth
        )
    
    async def scan_destination_directory(self, recursive: bool = True, max_depth: int = 3) -> DirectoryScanResult:
        """Scan the configured destination directory.""" 
        return await self._scan_directory(
            self._settings.destination_directory,
            description="destination",
            recursive=recursive,
            max_depth=max_depth
        )
    
    async def scan_custom_directory(self, directory_path: str, recursive: bool = True, max_depth: int = 3) -> DirectoryScanResult:
        """Scan a custom directory path."""
        return await self._scan_directory(
            directory_path, 
            description="custom",
            recursive=recursive,
            max_depth=max_depth
        )
    
    async def _scan_directory(self, directory_path: str, description: str = "directory", 
                            recursive: bool = True, max_depth: int = 3) -> DirectoryScanResult:
        """
        Internal method to scan a directory with timeout protection.
        
        Args:
            directory_path: Path to scan
            description: Description for logging
            recursive: Whether to scan subdirectories recursively
            max_depth: Maximum recursion depth
            
        Returns:
            DirectoryScanResult with scan results
        """
        start_time = datetime.now()
        
        try:
            scan_mode = "recursive" if recursive else "flat"
            logging.info(f"Starting {description} directory scan ({scan_mode}): {directory_path}")
            
            # Wrap the entire scan operation in a timeout
            result = await asyncio.wait_for(
                self._perform_directory_scan(directory_path, recursive=recursive, max_depth=max_depth),
                timeout=self._scan_timeout
            )
            
            scan_duration = (datetime.now() - start_time).total_seconds()
            result.scan_duration_seconds = scan_duration
            
            logging.info(
                f"{description.title()} scan completed: {result.total_items} items "
                f"({result.total_files} files, {result.total_directories} dirs) "
                f"in {scan_duration:.2f}s"
            )
            
            return result
            
        except asyncio.TimeoutError:
            scan_duration = (datetime.now() - start_time).total_seconds()
            logging.warning(f"{description.title()} directory scan timed out after {scan_duration:.1f}s")
            
            return DirectoryScanResult(
                path=directory_path,
                is_accessible=False,
                scan_duration_seconds=scan_duration,
                error_message=f"Scan timed out after {self._scan_timeout}s"
            )
            
        except Exception as e:
            scan_duration = (datetime.now() - start_time).total_seconds()
            logging.error(f"Error scanning {description} directory {directory_path}: {e}")
            
            return DirectoryScanResult(
                path=directory_path,
                is_accessible=False,
                scan_duration_seconds=scan_duration,
                error_message=str(e)
            )
    
    async def _perform_directory_scan(self, directory_path: str, recursive: bool = True, 
                                     max_depth: int = 3, current_depth: int = 0) -> DirectoryScanResult:
        """
        Perform the actual directory scan operation.
        
        Args:
            directory_path: Path to scan
            recursive: Whether to scan subdirectories
            max_depth: Maximum recursion depth
            current_depth: Current recursion level
        
        This method does the heavy lifting of scanning directories and collecting metadata.
        """
        # Check depth limit
        if current_depth > max_depth:
            logging.debug(f"Max depth ({max_depth}) reached at {directory_path}")
            return DirectoryScanResult(
                path=directory_path,
                is_accessible=False,
                error_message=f"Maximum scan depth ({max_depth}) exceeded"
            )
        
        # Check if directory exists and is accessible
        try:
            path_exists = await asyncio.wait_for(
                aiofiles.os.path.exists(directory_path),
                timeout=self._item_timeout
            )
            
            if not path_exists:
                return DirectoryScanResult(
                    path=directory_path,
                    is_accessible=False,
                    error_message="Directory does not exist"
                )
                
            path_is_dir = await asyncio.wait_for(
                aiofiles.os.path.isdir(directory_path),
                timeout=self._item_timeout
            )
            
            if not path_is_dir:
                return DirectoryScanResult(
                    path=directory_path,
                    is_accessible=False,
                    error_message="Path is not a directory"
                )
                
        except asyncio.TimeoutError:
            return DirectoryScanResult(
                path=directory_path,
                is_accessible=False,
                error_message="Directory accessibility check timed out"
            )
        
        # Scan directory contents
        items = []
        
        try:
            # Get directory listing with timeout
            dir_entries = await asyncio.wait_for(
                aiofiles.os.listdir(directory_path),
                timeout=self._item_timeout
            )
            
            # Process each entry with individual timeouts
            for entry_name in dir_entries:
                try:
                    item = await asyncio.wait_for(
                        self._get_item_metadata(directory_path, entry_name),
                        timeout=self._item_timeout
                    )
                    if item:
                        items.append(item)
                        
                except asyncio.TimeoutError:
                    logging.warning(f"Metadata fetch timed out for: {entry_name}")
                    # Create basic item without metadata
                    item_path = str(Path(directory_path) / entry_name)
                    items.append(DirectoryItem(
                        name=entry_name,
                        path=item_path,
                        is_directory=False,  # Default assumption
                        is_hidden=entry_name.startswith('.')
                    ))
                    
                except Exception as e:
                    logging.debug(f"Error getting metadata for {entry_name}: {e}")
                    # Skip items we can't read
                    continue
            
            # Recursive scanning if enabled and depth allows
            if recursive and current_depth < max_depth:
                # Find directories for recursive scanning
                subdirectories = [item for item in items if item.is_directory and not item.is_hidden]
                
                for subdir in subdirectories:
                    try:
                        # Recursively scan subdirectory
                        subdir_result = await asyncio.wait_for(
                            self._perform_directory_scan(
                                subdir.path, 
                                recursive=True, 
                                max_depth=max_depth, 
                                current_depth=current_depth + 1
                            ),
                            timeout=self._scan_timeout // (current_depth + 2)  # Reduced timeout for deeper levels
                        )
                        
                        # Add subdirectory items to our list
                        if subdir_result.is_accessible and subdir_result.items:
                            items.extend(subdir_result.items)
                            
                    except asyncio.TimeoutError:
                        logging.warning(f"Recursive scan timed out for subdirectory: {subdir.path}")
                        continue
                    except Exception as e:
                        logging.debug(f"Error during recursive scan of {subdir.path}: {e}")
                        continue
            
            return DirectoryScanResult(
                path=directory_path,
                is_accessible=True,
                items=items
            )
            
        except asyncio.TimeoutError:
            return DirectoryScanResult(
                path=directory_path,
                is_accessible=False,
                error_message="Directory listing timed out"
            )
        except Exception as e:
            return DirectoryScanResult(
                path=directory_path,
                is_accessible=False,
                error_message=f"Failed to list directory contents: {e}"
            )
    
    async def _get_item_metadata(self, parent_path: str, item_name: str) -> Optional[DirectoryItem]:
        """
        Get metadata for a single file or directory item.
        
        Args:
            parent_path: Parent directory path
            item_name: Name of the item
            
        Returns:
            DirectoryItem with metadata or None if failed
        """
        try:
            item_path = Path(parent_path) / item_name
            item_path_str = str(item_path)
            
            # Check if item is directory
            is_directory = await aiofiles.os.path.isdir(item_path_str)
            
            # Get file size (only for files)
            size_bytes = None
            if not is_directory:
                try:
                    stat_result = await aiofiles.os.stat(item_path_str)
                    size_bytes = stat_result.st_size
                except (OSError, AttributeError):
                    size_bytes = None
            
            # Get timestamps
            created_time = None
            modified_time = None
            try:
                stat_result = await aiofiles.os.stat(item_path_str)
                created_time = datetime.fromtimestamp(stat_result.st_ctime)
                modified_time = datetime.fromtimestamp(stat_result.st_mtime)
            except (OSError, AttributeError, ValueError):
                # Skip timestamp errors
                pass
            
            # Determine if hidden (starts with . on Unix-like systems)
            is_hidden = item_name.startswith('.')
            
            return DirectoryItem(
                name=item_name,
                path=item_path_str,
                is_directory=is_directory,
                is_hidden=is_hidden,
                size_bytes=size_bytes,
                created_time=created_time,
                modified_time=modified_time
            )
            
        except Exception as e:
            logging.debug(f"Failed to get metadata for {item_name}: {e}")
            return None
    
    def get_service_info(self) -> dict:
        """Get service configuration information."""
        return {
            "service": "DirectoryScannerService",
            "scan_timeout_seconds": self._scan_timeout,
            "item_timeout_seconds": self._item_timeout,
            "source_directory": self._settings.source_directory,
            "destination_directory": self._settings.destination_directory,
        }