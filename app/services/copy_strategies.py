"""
File Copy Strategy Framework

Defines abstract strategy interface and concrete implementations for different
file copying approaches: normal stable files vs growing files.
"""

import asyncio
import aiofiles
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict

from app.config import Settings
from app.models import FileStatus, TrackedFile
from app.services.state_manager import StateManager
from app.utils.file_operations import create_temp_file_path
from app.utils.progress_utils import should_report_progress_with_bytes, calculate_transfer_rate


class FileCopyStrategy(ABC):
    """
    Abstract base class for file copying strategies.
    
    Implements the Strategy pattern to allow different copying approaches:
    - NormalFileCopyStrategy: Traditional stable file copying
    - GrowingFileCopyStrategy: Streaming copy for files being written
    """
    
    def __init__(self, settings: Settings, state_manager: StateManager):
        self.settings = settings
        self.state_manager = state_manager
        self.logger = logging.getLogger(self.__class__.__name__)
    
    @abstractmethod
    async def copy_file(self, source_path: str, dest_path: str, tracked_file: TrackedFile) -> bool:
        """
        Copy a file using this strategy.
        
        Args:
            source_path: Source file path
            dest_path: Destination file path
            tracked_file: TrackedFile object for progress tracking
            
        Returns:
            True if copy was successful, False otherwise
        """
        pass
    
    @abstractmethod
    def supports_file(self, tracked_file: TrackedFile) -> bool:
        """
        Check if this strategy can handle the given file.
        
        Args:
            tracked_file: File to check
            
        Returns:
            True if this strategy supports the file
        """
        pass


class NormalFileCopyStrategy(FileCopyStrategy):
    """
    Traditional file copying strategy for stable files.
    
    Copies files that are completely written and stable.
    Uses the existing proven copy logic.
    """
    
    def supports_file(self, tracked_file: TrackedFile) -> bool:
        """Normal strategy supports all non-growing files"""
        return not tracked_file.is_growing_file
    
    async def copy_file(self, source_path: str, dest_path: str, tracked_file: TrackedFile) -> bool:
        """
        Copy a complete stable file.
        
        Uses traditional copy approach with optional temporary file and verification.
        """
        temp_dest_path = None
        
        try:
            self.logger.info(f"Starting normal copy: {os.path.basename(source_path)}")
            
            # Update status to copying
            await self.state_manager.update_file_status(
                source_path,
                FileStatus.COPYING,
                copy_progress=0.0
            )
            
            # Ensure destination directory exists (important for template system)
            dest_dir = Path(dest_path).parent
            dest_dir.mkdir(parents=True, exist_ok=True)
            self.logger.debug(f"Ensured destination directory exists: {dest_dir}")
            
            # Use temporary file if configured to do so
            if self.settings.use_temporary_file:
                temp_dest_path = create_temp_file_path(Path(dest_path))
                copy_dest_path = temp_dest_path
                self.logger.debug(f"Using temporary file: {temp_dest_path}")
            else:
                copy_dest_path = dest_path
                self.logger.debug(f"Using direct copy to: {dest_path}")
            
            # Perform the copy with progress tracking
            success = await self._copy_with_progress(source_path, copy_dest_path, tracked_file)
            
            if success:
                # Verify file integrity
                if await self._verify_file_integrity(source_path, copy_dest_path):
                    # If using temp file, rename it to final destination
                    if self.settings.use_temporary_file and temp_dest_path:
                        os.rename(temp_dest_path, dest_path)
                        self.logger.debug(f"Renamed temp file to final destination: {dest_path}")
                    
                    # Try to delete source file, but don't fail if it's locked
                    try:
                        os.remove(source_path)
                        self.logger.debug(f"Source file deleted: {os.path.basename(source_path)}")
                    except (OSError, PermissionError) as e:
                        self.logger.warning(f"Could not delete source file (may still be in use): {os.path.basename(source_path)} - {e}")
                        # Continue with completion even if deletion fails
                    
                    # Update status to completed
                    await self.state_manager.update_file_status(
                        source_path,
                        FileStatus.COMPLETED,
                        copy_progress=100.0,
                        destination_path=dest_path
                    )
                    
                    self.logger.info(f"Normal copy completed: {os.path.basename(source_path)}")
                    return True
                else:
                    self.logger.error(f"File integrity verification failed: {source_path}")
                    return False
            else:
                self.logger.error(f"Copy operation failed: {source_path}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error in normal copy strategy: {e}")
            return False
        finally:
            # Cleanup temporary file if it exists
            if temp_dest_path and os.path.exists(temp_dest_path):
                try:
                    os.remove(temp_dest_path)
                except Exception as e:
                    self.logger.warning(f"Failed to cleanup temp file {temp_dest_path}: {e}")
    
    async def _copy_with_progress(self, source_path: str, dest_path: str, tracked_file: TrackedFile) -> bool:
        """Copy file with progress updates using utility functions"""
        try:
            # Use optimized chunk size based on file size
            file_size_gb = tracked_file.file_size / (1024 * 1024 * 1024)
            if file_size_gb >= self.settings.large_file_threshold_gb:
                chunk_size = self.settings.large_file_chunk_size_kb * 1024  # 2MB for large files
                self.logger.debug(f"Using large file chunk size: {chunk_size // 1024}KB for {file_size_gb:.1f}GB file")
            else:
                chunk_size = self.settings.normal_file_chunk_size_kb * 1024  # 1MB for normal files
                self.logger.debug(f"Using normal file chunk size: {chunk_size // 1024}KB for {file_size_gb:.1f}GB file")
            
            bytes_copied = 0
            total_size = tracked_file.file_size
            last_progress_reported = -1
            
            # Track copy speed
            from datetime import datetime
            copy_start_time = datetime.now()
            
            async with aiofiles.open(source_path, 'rb') as src:
                async with aiofiles.open(dest_path, 'wb') as dst:
                    while True:
                        chunk = await src.read(chunk_size)
                        if not chunk:
                            break
                        
                        await dst.write(chunk)
                        bytes_copied += len(chunk)
                        
                        # Use utility function to determine if we should report progress
                        should_update, current_percent = should_report_progress_with_bytes(
                            bytes_copied, 
                            total_size, 
                            last_progress_reported, 
                            self.settings.copy_progress_update_interval
                        )
                        
                        if should_update:
                            # Calculate transfer rate using utility function
                            elapsed_seconds = (datetime.now() - copy_start_time).total_seconds()
                            transfer_rate = calculate_transfer_rate(bytes_copied, elapsed_seconds)
                            copy_speed_mbps = transfer_rate / (1024 * 1024)  # Convert to MB/s
                            
                            await self.state_manager.update_file_status(
                                source_path,
                                FileStatus.COPYING,
                                copy_progress=float(current_percent),
                                bytes_copied=bytes_copied,
                                copy_speed_mbps=copy_speed_mbps
                            )
                            last_progress_reported = current_percent
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error copying file {source_path}: {e}")
            return False
    
    async def _verify_file_integrity(self, source_path: str, dest_path: str) -> bool:
        """Verify that source and destination files are identical"""
        try:
            source_size = os.path.getsize(source_path)
            dest_size = os.path.getsize(dest_path)
            
            if source_size != dest_size:
                self.logger.error(f"Size mismatch: source={source_size}, dest={dest_size}")
                return False
            
            # Could add checksum verification here if needed
            return True
            
        except Exception as e:
            self.logger.error(f"Error verifying file integrity: {e}")
            return False


class GrowingFileCopyStrategy(FileCopyStrategy):
    """
    Growing file copying strategy for files being written.
    
    Copies files while they are still growing, maintaining a safety margin
    behind the write head to avoid conflicts.
    """
    
    def supports_file(self, tracked_file: TrackedFile) -> bool:
        """Growing strategy supports files marked as growing"""
        return tracked_file.is_growing_file
    
    async def copy_file(self, source_path: str, dest_path: str, tracked_file: TrackedFile) -> bool:
        """
        Copy a growing file with streaming approach.
        
        Monitors file growth and copies data while maintaining safety margin.
        """
        temp_dest_path = None
        
        try:
            self.logger.info(f"Starting growing copy: {os.path.basename(source_path)} "
                           f"(rate: {tracked_file.growth_rate_mbps:.2f}MB/s)")
            
            # Ensure destination directory exists (important for template system)
            dest_dir = Path(dest_path).parent
            dest_dir.mkdir(parents=True, exist_ok=True)
            self.logger.debug(f"Ensured destination directory exists: {dest_dir}")
            
            # Use temporary file if configured to do so
            if self.settings.use_temporary_file:
                temp_dest_path = create_temp_file_path(Path(dest_path))
                copy_dest_path = temp_dest_path
                self.logger.debug(f"Using temporary file for growing copy: {temp_dest_path}")
            else:
                copy_dest_path = dest_path
                self.logger.debug(f"Using direct growing copy to: {dest_path}")
            
            # Perform growing copy (status already set by FileCopyService)
            success = await self._copy_growing_file(source_path, copy_dest_path, tracked_file)
            
            if success:
                # Switch to normal copy mode for final data
                self.logger.info(f"Switching to normal copy mode: {os.path.basename(source_path)}")
                
                await self.state_manager.update_file_status(
                    source_path,
                    FileStatus.COPYING
                )
                
                # Finish copying any remaining data
                final_success = await self._finish_normal_copy(source_path, copy_dest_path, tracked_file)
                
                if final_success:
                    # Verify and finalize
                    if await self._verify_file_integrity(source_path, copy_dest_path):
                        # If using temp file, rename it to final destination
                        if self.settings.use_temporary_file and temp_dest_path:
                            os.rename(temp_dest_path, dest_path)
                            self.logger.debug(f"Renamed temp file to final destination: {dest_path}")
                        
                        # Try to delete source file, but don't fail if it's locked
                        try:
                            os.remove(source_path)
                            self.logger.debug(f"Source file deleted: {os.path.basename(source_path)}")
                        except (OSError, PermissionError) as e:
                            self.logger.warning(f"Could not delete source file (may still be in use): {os.path.basename(source_path)} - {e}")
                            # This is OK for growing files that may still be open by the writer
                        
                        await self.state_manager.update_file_status(
                            source_path,
                            FileStatus.COMPLETED,
                            copy_progress=100.0,
                            destination_path=dest_path
                        )
                        
                        self.logger.info(f"Growing copy completed: {os.path.basename(source_path)}")
                        return True
                    else:
                        self.logger.error(f"Growing copy verification failed: {source_path}")
                        return False
                else:
                    return False
            else:
                return False
                
        except Exception as e:
            self.logger.error(f"Error in growing copy strategy: {e}")
            return False
        finally:
            # Cleanup temporary file if it exists
            if temp_dest_path and os.path.exists(temp_dest_path):
                try:
                    os.remove(temp_dest_path)
                except Exception as e:
                    self.logger.warning(f"Failed to cleanup temp file {temp_dest_path}: {e}")
    
    async def _copy_growing_file(self, source_path: str, dest_path: str, tracked_file: TrackedFile) -> bool:
        """
        Copy growing file with safety margin.
        
        Continuously monitors file growth and copies data while staying behind write head.
        """
        try:
            chunk_size = self.settings.growing_file_chunk_size_kb * 1024  # Convert to bytes
            safety_margin_bytes = self.settings.growing_file_safety_margin_mb * 1024 * 1024
            poll_interval = self.settings.growing_file_poll_interval_seconds
            pause_ms = self.settings.growing_copy_pause_ms
            
            bytes_copied = 0
            last_file_size = 0
            no_growth_cycles = 0
            max_no_growth_cycles = self.settings.growing_file_growth_timeout_seconds // poll_interval
            
            # Open destination file for writing
            async with aiofiles.open(dest_path, 'wb') as dst:
                
                while True:
                    # Get current file size
                    try:
                        current_file_size = os.path.getsize(source_path)
                    except OSError:
                        self.logger.warning(f"Cannot access source file: {source_path}")
                        break
                    
                    # Check if file is still growing
                    if current_file_size > last_file_size:
                        # File is growing - reset no-growth counter
                        no_growth_cycles = 0
                        last_file_size = current_file_size
                    else:
                        # File not growing - increment counter
                        no_growth_cycles += 1
                        
                        if no_growth_cycles >= max_no_growth_cycles:
                            self.logger.info(f"File stopped growing: {os.path.basename(source_path)}")
                            break
                    
                    # Calculate safe copy position (stay behind write head)
                    safe_copy_to = max(0, current_file_size - safety_margin_bytes)
                    
                    if safe_copy_to > bytes_copied:
                        # Copy new data
                        bytes_to_copy = safe_copy_to - bytes_copied
                        
                        async with aiofiles.open(source_path, 'rb') as src:
                            await src.seek(bytes_copied)
                            
                            while bytes_to_copy > 0:
                                read_size = min(chunk_size, bytes_to_copy)
                                chunk = await src.read(read_size)
                                
                                if not chunk:
                                    break
                                
                                await dst.write(chunk)
                                chunk_len = len(chunk)
                                bytes_copied += chunk_len
                                bytes_to_copy -= chunk_len
                                
                                # Calculate progress and copy speed using utilities
                                copy_ratio = (bytes_copied / current_file_size) * 100 if current_file_size > 0 else 0
                                
                                # Calculate transfer rate using utility function
                                from datetime import datetime
                                current_time = datetime.now()
                                if not hasattr(self, '_copy_start_time'):
                                    self._copy_start_time = current_time
                                    self._copy_start_bytes = bytes_copied
                                
                                elapsed_seconds = (current_time - self._copy_start_time).total_seconds()
                                transfer_rate = calculate_transfer_rate(
                                    bytes_copied - self._copy_start_bytes, 
                                    elapsed_seconds
                                )
                                copy_speed_mbps = transfer_rate / (1024 * 1024)  # Convert to MB/s
                                
                                # Standard update for alle copy modes - ingen special growing fields
                                await self.state_manager.update_file_status(
                                    source_path,
                                    FileStatus.GROWING_COPY,
                                    copy_progress=copy_ratio,
                                    bytes_copied=bytes_copied,
                                    file_size=current_file_size,
                                    copy_speed_mbps=copy_speed_mbps
                                )
                                
                                # Throttle to avoid overwhelming disk I/O
                                if pause_ms > 0:
                                    await asyncio.sleep(pause_ms / 1000)
                    else:
                        # No new data to copy, but update progress
                        copy_ratio = (bytes_copied / current_file_size) * 100 if current_file_size > 0 else 0
                        
                        await self.state_manager.update_file_status(
                            source_path,
                            FileStatus.GROWING_COPY,
                            copy_progress=copy_ratio,
                            bytes_copied=bytes_copied,
                            file_size=current_file_size
                        )
                    
                    # Wait before next growth check
                    await asyncio.sleep(poll_interval)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error in growing file copy: {e}")
            return False
    
    async def _finish_normal_copy(self, source_path: str, dest_path: str, tracked_file: TrackedFile) -> bool:
        """Finish copying remaining data after growth stopped"""
        try:
            # Get final file size
            final_size = os.path.getsize(source_path)
            bytes_already_copied = tracked_file.bytes_copied
            
            if bytes_already_copied >= final_size:
                # Already copied everything
                return True
            
            # Use optimized chunk size for final copy
            file_size_gb = final_size / (1024 * 1024 * 1024)
            if file_size_gb >= self.settings.large_file_threshold_gb:
                chunk_size = self.settings.large_file_chunk_size_kb * 1024  # 2MB for large files
            else:
                chunk_size = self.settings.normal_file_chunk_size_kb * 1024  # 1MB for normal files
            
            async with aiofiles.open(source_path, 'rb') as src:
                async with aiofiles.open(dest_path, 'ab') as dst:  # Append mode
                    await src.seek(bytes_already_copied)
                    
                    while True:
                        chunk = await src.read(chunk_size)
                        if not chunk:
                            break
                        
                        await dst.write(chunk)
                        bytes_already_copied += len(chunk)
                        
                        # Update progress
                        progress = (bytes_already_copied / final_size) * 100
                        
                        await self.state_manager.update_file_status(
                            source_path,
                            FileStatus.COPYING,
                            copy_progress=progress,
                            bytes_copied=bytes_already_copied
                        )
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error finishing normal copy: {e}")
            return False
    
    async def _verify_file_integrity(self, source_path: str, dest_path: str) -> bool:
        """Verify that source and destination files are identical"""
        try:
            source_size = os.path.getsize(source_path)
            dest_size = os.path.getsize(dest_path)
            
            if source_size != dest_size:
                self.logger.error(f"Size mismatch: source={source_size}, dest={dest_size}")
                return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error verifying file integrity: {e}")
            return False


class CopyStrategyFactory:
    """
    Factory for creating appropriate copy strategies.
    
    Determines which strategy to use based on file characteristics and settings.
    Supports both traditional and resumable copy strategies.
    """
    
    def __init__(self, settings: Settings, state_manager: StateManager, enable_resume: bool = True):
        self.settings = settings
        self.state_manager = state_manager
        self.enable_resume = enable_resume
        
        # Initialize strategies
        if enable_resume:
            # Import resume strategies
            from app.utils.resumable_copy_strategies import (
                ResumableNormalFileCopyStrategy, 
                ResumableGrowingFileCopyStrategy,
                CONSERVATIVE_CONFIG
            )
            self.normal_strategy = ResumableNormalFileCopyStrategy(
                settings=settings, 
                state_manager=state_manager,
                resume_config=CONSERVATIVE_CONFIG
            )
            self.growing_strategy = ResumableGrowingFileCopyStrategy(
                settings=settings, 
                state_manager=state_manager,
                resume_config=CONSERVATIVE_CONFIG
            )
        else:
            # Traditional strategies
            self.normal_strategy = NormalFileCopyStrategy(settings, state_manager)
            self.growing_strategy = GrowingFileCopyStrategy(settings, state_manager)
    
    def get_strategy(self, tracked_file: TrackedFile) -> FileCopyStrategy:
        """
        Select appropriate copy strategy for the given file.
        
        Args:
            tracked_file: File to copy
            
        Returns:
            Appropriate copy strategy
        """
        # Debug logging
        import logging
        logger = logging.getLogger(__name__)
        
        # Check if growing file support is enabled
        if self.settings.enable_growing_file_support:
            # Try growing strategy first
            supports_growing = self.growing_strategy.supports_file(tracked_file)
            logger.debug(f"Strategy selection for {tracked_file.file_path}: "
                        f"is_growing_file={tracked_file.is_growing_file}, "
                        f"status={tracked_file.status}, "
                        f"supports_growing={supports_growing}")
            
            if supports_growing:
                logger.info(f"Selected GrowingFileCopyStrategy for {tracked_file.file_path}")
                return self.growing_strategy
        
        # Fall back to normal strategy
        logger.info(f"Selected NormalFileCopyStrategy for {tracked_file.file_path}")
        return self.normal_strategy
    
    def get_available_strategies(self) -> Dict[str, FileCopyStrategy]:
        """Get all available strategies"""
        strategies = {"normal": self.normal_strategy}
        
        if self.settings.enable_growing_file_support:
            strategies["growing"] = self.growing_strategy
        
        return strategies