"""
Query handlers for log file management operations.
Handles read-only operations for system log files.
"""
import asyncio
from pathlib import Path
from typing import List, Dict, Any
import logging
from fastapi import HTTPException, status
from fastapi.responses import FileResponse, Response
import aiofiles
import aiofiles.os

from app.dependencies.core import get_settings
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

    def _safe_log_path(self, filename: str) -> Path:
        """Resolve a log filename to a safe path within the logs directory."""
        logs_dir = Path(self.settings.log_directory).resolve()
        file_path = (logs_dir / filename).resolve()
        if not file_path.is_relative_to(logs_dir):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
        return file_path

    async def _assert_file_exists(
        self, file_path: Path, filename: str, *, check_is_file: bool = True
    ) -> None:
        """Non-blocking existence / is-file check using aiofiles.os."""
        if not await aiofiles.os.path.exists(str(file_path)):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Log file '{filename}' not found",
            )
        if check_is_file and not await aiofiles.os.path.isfile(str(file_path)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"'{filename}' is not a file",
            )

    @staticmethod
    def _list_log_files_sync(logs_dir: Path) -> list[dict[str, Any]]:
        """Synchronous helper — meant to run inside asyncio.to_thread."""
        if not logs_dir.exists():
            return []

        log_files: list[dict[str, Any]] = []
        for file_path in logs_dir.iterdir():
            if file_path.is_file() and file_path.suffix == '.log' or (
                file_path.is_file() and '.log.' in file_path.name
            ):
                stat = file_path.stat()
                size_bytes = stat.st_size
                size_mb = round(size_bytes / (1024 * 1024), 2)
                modified_time_ms = int(stat.st_mtime * 1000)

                log_files.append({
                    "filename": file_path.name,
                    "size": size_bytes,
                    "size_mb": size_mb,
                    "modified": stat.st_mtime,
                    "modified_time": modified_time_ms,
                    "path": str(file_path),
                    "is_current": file_path.name in (
                        "file_agent.log",
                        "audio_recording.log",
                    )
                })

        log_files.sort(key=lambda x: float(x.get("modified", 0)), reverse=True)
        return log_files

    async def handle_list_log_files(self, query: ListLogFilesQuery) -> List[Dict[str, Any]]:
        """
        List all available log files in the logs directory.
        
        Returns:
            List of log file information dictionaries
        """
        logs_dir = Path(self.settings.log_directory)
        return await asyncio.to_thread(self._list_log_files_sync, logs_dir)
    
    async def handle_get_log_content(self, query: GetLogContentQuery) -> Dict[str, Any]:
        """
        Get the full content of a log file.
        REVERSED: Shows newest lines first (bottom of file first).
        
        Args:
            query: GetLogContentQuery with filename
            
        Returns:
            Dictionary with file content and metadata
        """
        file_path = self._safe_log_path(query.filename)
        await self._assert_file_exists(file_path, query.filename)
        
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
        except HTTPException:
            raise
        except Exception as e:
            logging.error(f"Error reading log file: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error reading log file"
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
        file_path = self._safe_log_path(query.filename)
        await self._assert_file_exists(file_path, query.filename, check_is_file=False)
        
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
        except HTTPException:
            raise
        except Exception as e:
            logging.error(f"Error reading log file chunk: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error reading log file chunk"
            )
    
    async def handle_download_log_file(self, query: DownloadLogFileQuery) -> Response:
        """
        Prepare a log file for download.
        
        For active log files, creates a snapshot to avoid file locking issues.
        
        Args:
            query: DownloadLogFileQuery with filename
            
        Returns:
            FileResponse for file download
        """
        file_path = self._safe_log_path(query.filename)
        await self._assert_file_exists(file_path, query.filename)
        
        try:
            # For growing/active log files, we read content into memory
            # to avoid Chrome download issues with locked files
            
            # Read the current content into memory
            async with aiofiles.open(file_path, mode='r', encoding='utf-8', errors='replace') as source_file:
                content = await source_file.read()
            
            # Always use .txt extension for download and force download behavior
            download_filename = query.filename
            if not download_filename.endswith('.txt'):
                # Add .txt extension if not already present
                download_filename = f"{query.filename}.txt"
            
            # Create a memory-based response instead of file-based
            return Response(
                content=content.encode('utf-8'),
                media_type='application/octet-stream', # Force download instead of browser preview
                headers={
                    "Content-Disposition": f'attachment; filename="{download_filename}"',
                    "Content-Type": "text/plain; charset=utf-8",
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                    "Content-Length": str(len(content.encode('utf-8')))
                }
            )
            
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error preparing log file for download: {str(e)}"
            )