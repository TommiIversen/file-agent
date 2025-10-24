import asyncio
import logging
from datetime import datetime
from pathlib import Path

from starlette.responses import StreamingResponse

from ..config import Settings
from ..dependencies import get_settings


from fastapi import APIRouter, HTTPException, Depends

router = APIRouter(prefix="/api", tags=["logfile"])



@router.get("/log-files")
async def list_log_files(settings: Settings = Depends(get_settings)):
    """List available log files"""

    try:
        logging.info("Log files list requested", extra={"operation": "api_list_log_files"})


        logs_directory = settings.log_directory

        # Use async wrapper for all file operations to prevent blocking
        def _sync_get_log_files():
            if not logs_directory.exists():
                return None, "Log directory does not exist"

            log_files_async = []

            # Find all log files in the directory
            for log_file in logs_directory.glob("*.log*"):
                if log_file.is_file():
                    try:
                        stat = log_file.stat()
                        log_files_async.append({
                            "filename": log_file.name,
                            "size_bytes": stat.st_size,
                            "size_mb": round(stat.st_size / (1024 * 1024), 2),
                            "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                            "url": f"/logs/{log_file.name}",
                            "is_current": log_file.name == Path(settings.log_file_path).name
                        })
                    except Exception as e:
                        logging.warning(f"Failed to get stats for {log_file}: {e}")

            return log_files_async, None

        # Execute with timeout to prevent blocking the event loop
        try:
            log_files, error_msg = await asyncio.wait_for(
                asyncio.to_thread(_sync_get_log_files),
                timeout=3.0  # 3 second timeout
            )
        except asyncio.TimeoutError:
            logging.warning("Log files listing timed out")
            return {
                "success": False,
                "message": "Log directory scan timed out",
                "log_files": []
            }

        if error_msg:
            return {
                "success": False,
                "message": error_msg,
                "log_files": []
            }

        # Sort by modification time, newest first
        log_files.sort(key=lambda x: x["modified_time"], reverse=True)

        return {
            "success": True,
            "message": f"Found {len(log_files)} log files",
            "log_directory": str(logs_directory),
            "log_files": log_files
        }

    except Exception as e:
        logging.error(f"Failed to list log files: {e}")
        return {
            "success": False,
            "message": f"Failed to list log files: {str(e)}",
            "log_files": []
        }


@router.get("/log-content/{filename}")
async def get_log_content(filename: str, settings: Settings = Depends(get_settings)):
    """
    Get log file content with special handling for active log files.
    This endpoint handles the issue where active log files can't be served
    via StaticFiles due to concurrent writes causing Content-Length errors.
    """
    try:

        logs_directory = Path("logs")
        log_file_path = logs_directory / filename

        # Security check - ensure the file is within the logs directory
        def _sync_security_check():
            return str(log_file_path.resolve()).startswith(str(logs_directory.resolve()))

        try:
            is_secure = await asyncio.wait_for(
                asyncio.to_thread(_sync_security_check),
                timeout=1.0
            )
            if not is_secure:
                raise HTTPException(status_code=400, detail="Invalid file path")
        except asyncio.TimeoutError:
            raise HTTPException(status_code=500, detail="Security check timed out")

        # Use async wrapper for file operations
        def _sync_read_log_file():
            if not log_file_path.exists():
                return None, "Log file not found", None

            if not log_file_path.is_file():
                return None, "Path is not a file", None

            # Check if this is the current active log file
            current_log_name = Path(settings.log_file_path).name
            is_current_log = filename == current_log_name

            try:
                # For active log files, read with special handling
                if is_current_log:
                    # Read the file in chunks to handle concurrent writes better
                    content_chunks = []
                    with open(log_file_path, 'r', encoding='utf-8', errors='replace') as f:
                        while True:
                            chunk = f.read(8192)  # Read in 8KB chunks
                            if not chunk:
                                break
                            content_chunks.append(chunk)
                    content = ''.join(content_chunks)
                else:
                    # For archived log files, normal read is fine
                    with open(log_file_path, 'r', encoding='utf-8', errors='replace') as f:
                        content = f.read()

                # Get file stats
                stat = log_file_path.stat()

                return {
                    "content": content,
                    "stat": stat,
                    "is_current_log": is_current_log
                }, None, None

            except Exception as e:
                return None, f"Error reading log file: {str(e)}", None

        # Execute with timeout to prevent blocking
        try:
            result, error_msg, _ = await asyncio.wait_for(
                asyncio.to_thread(_sync_read_log_file),
                timeout=5.0  # 5 second timeout for file read
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=500, detail="Log file read timed out")

        if error_msg == "Log file not found":
            raise HTTPException(status_code=404, detail="Log file not found")
        elif error_msg == "Path is not a file":
            raise HTTPException(status_code=400, detail="Path is not a file")
        elif error_msg:
            raise HTTPException(status_code=500, detail=error_msg)

        return {
            "success": True,
            "filename": filename,
            "content": result["content"],
            "size_bytes": result["stat"].st_size,
            "size_mb": round(result["stat"].st_size / (1024 * 1024), 2),
            "modified_time": datetime.fromtimestamp(result["stat"].st_mtime).isoformat(),
            "is_current": result["is_current_log"],
            "lines": result["content"].count('\n') + 1 if result["content"] else 0
        }

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Unexpected error reading log file {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.get("/log-content/{filename}/chunk")
async def get_log_content_chunk(
    filename: str,
    offset: int = 0,
    limit: int = 1000,
    direction: str = "forward",
    settings: Settings = Depends(get_settings)
):
    """
    Get log file content in chunks for better performance with large files.

    Args:
        filename: Name of the log file
        offset: Starting line number (0-based)
        limit: Maximum number of lines to return
        direction: "forward" to read from offset downward, "backward" to read from offset upward

    Returns:
        JSON with chunk data including lines, total line count, and pagination info
    """
    try:
        logs_directory = Path("logs")
        log_file_path = logs_directory / filename

        # Security check
        if not str(log_file_path.resolve()).startswith(str(logs_directory.resolve())):
            raise HTTPException(status_code=400, detail="Invalid file path")

        if not log_file_path.exists():
            raise HTTPException(status_code=404, detail="Log file not found")

        if not log_file_path.is_file():
            raise HTTPException(status_code=400, detail="Path is not a file")

        # Validate parameters
        if limit <= 0 or limit > 10000:
            raise HTTPException(status_code=400, detail="Limit must be between 1 and 10000")

        if offset < 0:
            raise HTTPException(status_code=400, detail="Offset must be >= 0")

        if direction not in ["forward", "backward"]:
            raise HTTPException(status_code=400, detail="Direction must be 'forward' or 'backward'")

        # Check if this is the current active log file
        current_log_name = Path(settings.log_file_path).name
        is_current_log = filename == current_log_name

        # Read the file and split into lines
        try:
            if is_current_log:
                # For active log files, read with special handling
                content_chunks = []
                with open(log_file_path, 'r', encoding='utf-8', errors='replace') as f:
                    while True:
                        chunk = f.read(8192)
                        if not chunk:
                            break
                        content_chunks.append(chunk)
                content = ''.join(content_chunks)
            else:
                # For archived log files, normal read is fine
                with open(log_file_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()

        except Exception as e:
            logging.error(f"Error reading log file {filename}: {e}")
            raise HTTPException(status_code=500, detail=f"Error reading log file: {str(e)}")

        # Split into lines
        all_lines = content.split('\n')
        total_lines = len(all_lines)

        # Calculate chunk based on direction
        if direction == "forward":
            # Read from offset downward
            start_idx = min(offset, total_lines)
            end_idx = min(start_idx + limit, total_lines)
            lines = all_lines[start_idx:end_idx]
            actual_offset = start_idx
        else:
            # Read from offset upward (backward)
            end_idx = min(offset + 1, total_lines)
            start_idx = max(0, end_idx - limit)
            lines = all_lines[start_idx:end_idx]
            actual_offset = start_idx

        # Calculate pagination info
        has_more_forward = (actual_offset + len(lines)) < total_lines
        has_more_backward = actual_offset > 0

        # Get file stats
        stat = log_file_path.stat()

        return {
            "success": True,
            "filename": filename,
            "lines": lines,
            "chunk_info": {
                "offset": actual_offset,
                "count": len(lines),
                "requested_limit": limit,
                "direction": direction,
                "total_lines": total_lines,
                "has_more_forward": has_more_forward,
                "has_more_backward": has_more_backward,
                "next_forward_offset": actual_offset + len(lines) if has_more_forward else None,
                "next_backward_offset": max(0, actual_offset - limit) if has_more_backward else None
            },
            "file_info": {
                "size_bytes": stat.st_size,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "is_current": is_current_log
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Unexpected error reading log chunk for {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.get("/log-download/{filename}")
async def download_log_file(filename: str, settings: Settings = Depends(get_settings)):
    """
    Download a log file with proper streaming for large files.
    """
    try:
        logs_directory = Path("logs")
        log_file_path = logs_directory / filename

        # Security check
        if not str(log_file_path.resolve()).startswith(str(logs_directory.resolve())):
            raise HTTPException(status_code=400, detail="Invalid file path")

        if not log_file_path.exists():
            raise HTTPException(status_code=404, detail="Log file not found")

        if not log_file_path.is_file():
            raise HTTPException(status_code=400, detail="Path is not a file")

        # Check if this is the current active log file
        current_log_name = Path(settings.log_file_path).name
        is_current_log = filename == current_log_name

        def generate_file_stream():
            """Generate file content in chunks for streaming"""
            try:
                if is_current_log:
                    # For active log files, read the entire content at once to avoid
                    # issues with file growing during download
                    with open(log_file_path, 'rb') as f:
                        content = f.read()
                    yield content
                else:
                    # For archived log files, stream in chunks
                    with open(log_file_path, 'rb') as f:
                        while True:
                            chunk = f.read(8192)  # 8KB chunks
                            if not chunk:
                                break
                            yield chunk
            except Exception as e:
                logging.error(f"Error streaming log file {filename}: {e}")
                # Can't raise HTTPException in generator, so yield error message
                yield f"Error reading file: {str(e)}".encode('utf-8')

        # Get file size for Content-Length header
        file_size = log_file_path.stat().st_size

        # Create headers for download
        headers = {
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Type': 'text/plain; charset=utf-8',
        }

        # Only add Content-Length for non-active files to avoid streaming issues
        if not is_current_log:
            headers['Content-Length'] = str(file_size)

        # Add warning for current log files
        if is_current_log:
            headers['X-Warning'] = 'Current active log file - snapshot taken at download time'

        return StreamingResponse(
            generate_file_stream(),
            headers=headers,
            media_type='text/plain'
        )

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Unexpected error preparing download for {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
