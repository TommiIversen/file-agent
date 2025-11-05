"""
Query handlers for log file management operations.
Handles read-only operations for system log files.
"""
import mimetypes
from pathlib import Path
from typing import List, Dict, Any
from fastapi import HTTPException, status
from fastapi.responses import FileResponse
import aiofiles

from app.dependencies import get_settings
from app.domains.shared.queries.log_queries import (
    ListLogFilesQuery,
    GetLogContentQuery, 
    GetLogContentChunkQuery,
    DownloadLogFileQuery
)


class LogFileQueryHandler:
    """Handler for log file query operations."""
    
    def __init__(self):
        self.settings = get_settings()
    
    async def handle_list_log_files(self, query: ListLogFilesQuery) -> List[Dict[str, Any]]:
        """
        List all available log files in the logs directory.
        
        Returns:
            List of log file information dictionaries
        """
        logs_dir = Path(self.settings.log_directory)
        
        if not logs_dir.exists():
            return []
        
        log_files = []
        for file_path in logs_dir.iterdir():
            # Match files that start with log file prefix and are actual log files
            if file_path.is_file() and (file_path.name.startswith('file_agent.log')):
                stat = file_path.stat()
                size_bytes = stat.st_size
                size_mb = round(size_bytes / (1024 * 1024), 2)
                
                # Convert timestamp to milliseconds for JavaScript Date
                modified_time_ms = int(stat.st_mtime * 1000)
                
                log_files.append({
                    "filename": file_path.name,
                    "size": size_bytes,
                    "size_mb": size_mb,
                    "modified": stat.st_mtime,
                    "modified_time": modified_time_ms,  # JavaScript expects milliseconds
                    "path": str(file_path),
                    "is_current": file_path.name == "file_agent.log"  # Current log has no date suffix
                })
        
        # Sort by modification time, newest first
        log_files.sort(key=lambda x: x["modified"], reverse=True)
        return log_files
    
    async def handle_get_log_content(self, query: GetLogContentQuery) -> Dict[str, Any]:
        """
        Get the full content of a log file.
        REVERSED: Shows newest lines first (bottom of file first).
        
        Args:
            query: GetLogContentQuery with filename
            
        Returns:
            Dictionary with file content and metadata
        """
        logs_dir = Path(self.settings.log_directory)
        file_path = logs_dir / query.filename
        
        if not file_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Log file '{query.filename}' not found"
            )
        
        if not file_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"'{query.filename}' is not a file"
            )
        
        try:
            async with aiofiles.open(file_path, mode='r', encoding='utf-8', errors='replace') as f:
                content = await f.read()
            
            # REVERSE the content so newest lines come first
            lines = content.splitlines()
            lines.reverse()
            reversed_content = '\n'.join(lines)
                
            return {
                "filename": query.filename,
                "content": reversed_content,
                "size": len(reversed_content),
                "lines": len(lines)
            }
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error reading log file: {str(e)}"
            )
    
    async def handle_get_log_content_chunk(self, query: GetLogContentChunkQuery) -> Dict[str, Any]:
        """
        Get a chunk of log file content with pagination.
        REVERSED: Shows newest lines first (bottom of file first).
        
        Args:
            query: GetLogContentChunkQuery with filename, start, and limit
            
        Returns:
            Dictionary with chunk content and pagination metadata
        """
        logs_dir = Path(self.settings.log_directory)
        file_path = logs_dir / query.filename
        
        if not file_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Log file '{query.filename}' not found"
            )
        
        try:
            async with aiofiles.open(file_path, mode='r', encoding='utf-8', errors='replace') as f:
                content = await f.read()
                
            lines = content.splitlines()
            total_lines = len(lines)
            
            # REVERSE the lines so newest (bottom of file) comes first
            lines.reverse()
            
            # Calculate pagination (now on reversed lines)
            start = max(0, query.start)
            end = min(total_lines, start + query.limit)
            chunk_lines = lines[start:end]
            
            return {
                "filename": query.filename,
                "content": '\n'.join(chunk_lines),
                "start": start,
                "limit": query.limit,
                "returned": len(chunk_lines),
                "total_lines": total_lines,
                "has_more": end < total_lines
            }
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error reading log file chunk: {str(e)}"
            )
    
    async def handle_download_log_file(self, query: DownloadLogFileQuery) -> FileResponse:
        """
        Prepare a log file for download.
        
        Args:
            query: DownloadLogFileQuery with filename
            
        Returns:
            FileResponse for file download
        """
        logs_dir = Path(self.settings.log_directory)
        file_path = logs_dir / query.filename
        
        if not file_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Log file '{query.filename}' not found"
            )
        
        if not file_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"'{query.filename}' is not a file"
            )
        
        # Determine MIME type
        mime_type, _ = mimetypes.guess_type(str(file_path))
        if mime_type is None:
            mime_type = 'text/plain'
        
        return FileResponse(
            path=str(file_path),
            media_type=mime_type,
            filename=query.filename
        )