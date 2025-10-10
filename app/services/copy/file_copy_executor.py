"""
File Copy Executor Service for File Transfer Agent.

FileCopyExecutor håndterer den faktiske filkopiering med forskellige strategier:
- Direct copy: Direkte kopiering fra source til destination
- Temporary file copy: Kopiering til temp fil, derefter rename
- Progress tracking: Real-time progress callbacks
- Verification: Filstørrelse validering efter kopiering

Dette er en core service der extractes fra FileCopyService for at følge SOLID principper.
"""

import aiofiles
import logging
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from dataclasses import dataclass

from app.config import Settings
from app.utils.file_operations import validate_file_sizes, create_temp_file_path
from app.utils.progress_utils import should_report_progress_with_bytes


@dataclass
class CopyResult:
    """
    Result of a file copy operation.
    
    Provides comprehensive information about the copy operation including
    success status, performance metrics, and any error information.
    """
    success: bool
    source_path: Path
    destination_path: Path
    bytes_copied: int
    elapsed_seconds: float
    start_time: datetime
    end_time: datetime
    error_message: Optional[str] = None
    verification_successful: bool = True
    temp_file_used: bool = False
    temp_file_path: Optional[Path] = None
    
    @property
    def transfer_rate_bytes_per_sec(self) -> float:
        """Calculate transfer rate in bytes per second."""
        if self.elapsed_seconds <= 0:
            return 0.0
        return self.bytes_copied / self.elapsed_seconds
    
    @property
    def transfer_rate_mb_per_sec(self) -> float:
        """Calculate transfer rate in MB per second."""
        return self.transfer_rate_bytes_per_sec / (1024 * 1024)
    
    @property
    def size_mb(self) -> float:
        """Get file size in MB."""
        return self.bytes_copied / (1024 * 1024)
    
    def get_summary(self) -> str:
        """
        Get a human-readable summary of the copy operation.
        
        Returns:
            Formatted string with copy operation details
        """
        if self.success:
            return (
                f"Copy successful: {self.source_path.name} "
                f"({self.size_mb:.2f} MB in {self.elapsed_seconds:.2f}s, "
                f"{self.transfer_rate_mb_per_sec:.2f} MB/s)"
            )
        else:
            return (
                f"Copy failed: {self.source_path.name} - "
                f"{self.error_message or 'Unknown error'}"
            )


@dataclass
class CopyProgress:
    """
    Progress information for an ongoing copy operation.
    
    Used for progress callbacks during file copying.
    """
    bytes_copied: int
    total_bytes: int
    elapsed_seconds: float
    current_rate_bytes_per_sec: float
    
    @property
    def progress_percent(self) -> float:
        """Calculate completion percentage (0.0 to 100.0)."""
        if self.total_bytes <= 0:
            return 0.0
        return min(100.0, (self.bytes_copied / self.total_bytes) * 100.0)
    
    @property
    def progress_percent_int(self) -> int:
        """Get completion percentage as integer (0 to 100)."""
        return int(self.progress_percent)
    
    @property
    def remaining_bytes(self) -> int:
        """Calculate remaining bytes to copy."""
        return max(0, self.total_bytes - self.bytes_copied)
    
    @property
    def estimated_remaining_seconds(self) -> float:
        """Estimate remaining time in seconds based on current rate."""
        if self.current_rate_bytes_per_sec <= 0:
            return 0.0
        return self.remaining_bytes / self.current_rate_bytes_per_sec


class FileCopyExecutor:
    """
    Responsible for executing file copy operations with different strategies.
    
    Provides both direct and temporary file copy methods with:
    - Progress tracking through callbacks
    - File verification after copy
    - Detailed result reporting
    - Error handling and cleanup
    """
    
    def __init__(self, settings: Settings):
        """
        Initialize FileCopyExecutor with configuration.
        
        Args:
            settings: Application settings for copy configuration
        """
        self.settings = settings
        self._logger = logging.getLogger("app.copy_executor")
        
        # Copy configuration
        self.chunk_size = 64 * 1024  # 64KB chunks
        self.progress_update_interval = getattr(settings, 'copy_progress_update_interval', 1)
        
        self._logger.debug(f"FileCopyExecutor initialized with chunk_size={self.chunk_size}")
    
    async def copy_file(
        self, 
        source: Path, 
        dest: Path, 
        progress_callback: Optional[Callable[[CopyProgress], None]] = None
    ) -> CopyResult:
        """
        Copy file using the configured strategy (temp file or direct).
        
        Args:
            source: Source file path
            dest: Destination file path
            progress_callback: Optional callback for progress updates
            
        Returns:
            CopyResult with operation details and performance metrics
        """
        if self.settings.use_temporary_file:
            return await self.copy_with_temp_file(source, dest, progress_callback)
        else:
            return await self.copy_direct(source, dest, progress_callback)
    
    async def copy_with_temp_file(
        self, 
        source: Path, 
        dest: Path, 
        progress_callback: Optional[Callable[[CopyProgress], None]] = None
    ) -> CopyResult:
        """
        Copy file to a temporary location, then rename to final destination.
        
        This strategy provides atomic copy operations - the destination file
        either appears complete or not at all.
        
        Args:
            source: Source file path
            dest: Destination file path
            progress_callback: Optional callback for progress updates
            
        Returns:
            CopyResult with operation details
        """
        start_time = datetime.now()
        temp_path = create_temp_file_path(dest)
        
        try:
            self._logger.debug(f"Starting temp file copy: {source} -> {temp_path} -> {dest}")
            
            # Ensure destination directory exists
            dest.parent.mkdir(parents=True, exist_ok=True)
            
            # Copy to temporary file
            result = await self._perform_copy(source, temp_path, progress_callback, start_time)
            
            if not result.success:
                return result
            
            # Verify the temporary file
            if not await self.verify_copy(source, temp_path):
                # Cleanup temp file on verification failure
                if temp_path.exists():
                    temp_path.unlink()
                
                end_time = datetime.now()
                return CopyResult(
                    success=False,
                    source_path=source,
                    destination_path=dest,
                    bytes_copied=result.bytes_copied,
                    elapsed_seconds=(end_time - start_time).total_seconds(),
                    start_time=start_time,
                    end_time=end_time,
                    error_message="File verification failed after copy",
                    verification_successful=False,
                    temp_file_used=True,
                    temp_file_path=temp_path
                )
            
            # Rename temporary file to final destination
            temp_path.rename(dest)
            
            # Update result with final destination
            end_time = datetime.now()
            result.destination_path = dest
            result.end_time = end_time
            result.elapsed_seconds = (end_time - start_time).total_seconds()
            result.temp_file_used = True
            result.temp_file_path = temp_path
            
            self._logger.debug(f"Temp file copy completed successfully: {source} -> {dest}")
            return result
            
        except Exception as e:
            # Cleanup temp file on any error
            if temp_path.exists():
                try:
                    temp_path.unlink()
                    self._logger.debug(f"Cleaned up temp file after error: {temp_path}")
                except Exception:
                    pass
            
            end_time = datetime.now()
            error_msg = f"Temp file copy failed: {str(e)}"
            self._logger.error(error_msg)
            
            return CopyResult(
                success=False,
                source_path=source,
                destination_path=dest,
                bytes_copied=0,
                elapsed_seconds=(end_time - start_time).total_seconds(),
                start_time=start_time,
                end_time=end_time,
                error_message=error_msg,
                temp_file_used=True,
                temp_file_path=temp_path
            )
    
    async def copy_direct(
        self, 
        source: Path, 
        dest: Path, 
        progress_callback: Optional[Callable[[CopyProgress], None]] = None
    ) -> CopyResult:
        """
        Copy file directly to the destination path.
        
        This strategy writes directly to the final destination.
        Use with caution as partial files may be visible during copy.
        
        Args:
            source: Source file path
            dest: Destination file path
            progress_callback: Optional callback for progress updates
            
        Returns:
            CopyResult with operation details
        """
        start_time = datetime.now()
        
        try:
            self._logger.debug(f"Starting direct copy: {source} -> {dest}")
            
            # Ensure destination directory exists
            dest.parent.mkdir(parents=True, exist_ok=True)
            
            # Perform direct copy
            result = await self._perform_copy(source, dest, progress_callback, start_time)
            
            if result.success:
                # Verify the copied file
                if not await self.verify_copy(source, dest):
                    # Delete incomplete destination file
                    if dest.exists():
                        dest.unlink()
                    
                    end_time = datetime.now()
                    result.success = False
                    result.error_message = "File verification failed after copy"
                    result.verification_successful = False
                    result.end_time = end_time
                    result.elapsed_seconds = (end_time - start_time).total_seconds()
                else:
                    self._logger.debug(f"Direct copy completed successfully: {source} -> {dest}")
            
            return result
            
        except Exception as e:
            # Cleanup destination file on error
            if dest.exists():
                try:
                    dest.unlink()
                    self._logger.debug(f"Cleaned up destination file after error: {dest}")
                except Exception:
                    pass
            
            end_time = datetime.now()
            error_msg = f"Direct copy failed: {str(e)}"
            self._logger.error(error_msg)
            
            return CopyResult(
                success=False,
                source_path=source,
                destination_path=dest,
                bytes_copied=0,
                elapsed_seconds=(end_time - start_time).total_seconds(),
                start_time=start_time,
                end_time=end_time,
                error_message=error_msg
            )
    
    async def _perform_copy(
        self, 
        source: Path, 
        dest: Path, 
        progress_callback: Optional[Callable[[CopyProgress], None]],
        start_time: datetime
    ) -> CopyResult:
        """
        Perform the actual file copy with progress tracking.
        
        Args:
            source: Source file path
            dest: Destination file path
            progress_callback: Optional progress callback
            start_time: Copy operation start time
            
        Returns:
            CopyResult with copy details
        """
        file_size = source.stat().st_size
        bytes_copied = 0
        last_progress_reported = -1
        
        try:
            async with aiofiles.open(source, 'rb') as src, aiofiles.open(dest, 'wb') as dst:
                while True:
                    chunk = await src.read(self.chunk_size)
                    if not chunk:
                        break
                    
                    await dst.write(chunk)
                    bytes_copied += len(chunk)
                    
                    # Report progress if callback provided
                    if progress_callback:
                        current_time = datetime.now()
                        elapsed = (current_time - start_time).total_seconds()
                        
                        should_update, current_percent = should_report_progress_with_bytes(
                            bytes_copied, 
                            file_size, 
                            last_progress_reported, 
                            self.progress_update_interval
                        )
                        
                        if should_update:
                            current_rate = bytes_copied / elapsed if elapsed > 0 else 0
                            progress = CopyProgress(
                                bytes_copied=bytes_copied,
                                total_bytes=file_size,
                                elapsed_seconds=elapsed,
                                current_rate_bytes_per_sec=current_rate
                            )
                            
                            try:
                                progress_callback(progress)
                                last_progress_reported = current_percent
                            except Exception as e:
                                self._logger.warning(f"Progress callback error: {e}")
            
            end_time = datetime.now()
            elapsed_seconds = (end_time - start_time).total_seconds()
            
            return CopyResult(
                success=True,
                source_path=source,
                destination_path=dest,
                bytes_copied=bytes_copied,
                elapsed_seconds=elapsed_seconds,
                start_time=start_time,
                end_time=end_time
            )
            
        except Exception as e:
            end_time = datetime.now()
            elapsed_seconds = (end_time - start_time).total_seconds()
            
            return CopyResult(
                success=False,
                source_path=source,
                destination_path=dest,
                bytes_copied=bytes_copied,
                elapsed_seconds=elapsed_seconds,
                start_time=start_time,
                end_time=end_time,
                error_message=str(e)
            )
    
    async def verify_copy(self, source: Path, dest: Path) -> bool:
        """
        Verify that the file was copied correctly by comparing file sizes.
        
        Args:
            source: Source file path
            dest: Destination file path
            
        Returns:
            True if verification successful, False otherwise
        """
        try:
            if not dest.exists():
                self._logger.warning(f"Destination file does not exist: {dest}")
                return False
            
            source_size = source.stat().st_size
            dest_size = dest.stat().st_size
            
            is_valid = validate_file_sizes(source_size, dest_size)
            
            if is_valid:
                self._logger.debug(f"File verification successful: {source_size} bytes")
            else:
                self._logger.error(f"File size mismatch: source={source_size}, dest={dest_size}")
            
            return is_valid
            
        except Exception as e:
            self._logger.error(f"File verification error: {e}")
            return False
    
    def get_executor_info(self) -> dict:
        """
        Get information about the executor configuration.
        
        Returns:
            Dictionary with executor configuration details
        """
        return {
            "chunk_size": self.chunk_size,
            "progress_update_interval": self.progress_update_interval,
            "use_temporary_file": self.settings.use_temporary_file,
            "default_strategy": "temp_file" if self.settings.use_temporary_file else "direct"
        }