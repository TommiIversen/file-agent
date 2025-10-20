import asyncio
import aiofiles
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict

from app.config import Settings
from app.models import FileStatus, TrackedFile
from app.services.state_manager import StateManager
from app.services.copy.file_copy_executor import FileCopyExecutor, CopyProgress
from app.utils.file_operations import create_temp_file_path
from app.utils.progress_utils import calculate_transfer_rate


class FileCopyStrategy(ABC):
    def __init__(
        self,
        settings: Settings,
        state_manager: StateManager,
        file_copy_executor: FileCopyExecutor,
    ):
        self.settings = settings
        self.state_manager = state_manager

        self.file_copy_executor = file_copy_executor

    @abstractmethod
    async def copy_file(
        self, source_path: str, dest_path: str, tracked_file: TrackedFile
    ) -> bool:
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

    async def copy_file(
        self, source_path: str, dest_path: str, tracked_file: TrackedFile
    ) -> bool:
        """
        Copy a complete stable file using FileCopyExecutor.

        Delegates the actual copy operation to the executor and handles the result.
        """
        source = Path(source_path)
        dest = Path(dest_path)

        try:
            logging.info(f"Starting normal copy via executor: {source.name}")

            # Update status to copying - UUID precision (use existing tracked_file parameter)
            await self.state_manager.update_file_status_by_id(
                tracked_file.id, FileStatus.COPYING, copy_progress=0.0
            )

            # Create a progress callback that updates the state manager
            def progress_callback(progress: CopyProgress):
                asyncio.create_task(
                    self.state_manager.update_file_status_by_id(
                        tracked_file.id,
                        FileStatus.COPYING,
                        copy_progress=progress.progress_percent,
                        bytes_copied=progress.bytes_copied,
                        copy_speed_mbps=progress.current_rate_bytes_per_sec
                        / (1024 * 1024),
                    )
                )

            # Delegate the copy operation to the executor
            copy_result = await self.file_copy_executor.copy_file(
                source=source, dest=dest, progress_callback=progress_callback
            )

            if copy_result.success:
                logging.info(
                    f"Executor finished successfully for {source.name}. Verifying and finalizing."
                )

                # Final verification is handled by the executor, but we can double-check
                if not await self._verify_file_integrity(source_path, dest_path):
                    logging.error(f"Post-copy verification failed for {source.name}")
                    return False

                # Try to delete source file, but don't fail if it's locked
                try:
                    os.remove(source_path)
                    logging.debug(f"Source file deleted: {source.name}")
                except (OSError, PermissionError) as e:
                    logging.warning(
                        f"Could not delete source file (may still be in use): {source.name} - {e}"
                    )

                # Update status to completed - UUID precision
                await self.state_manager.update_file_status_by_id(
                    tracked_file.id,
                    FileStatus.COMPLETED,
                    copy_progress=100.0,
                    destination_path=dest_path,
                )

                logging.info(f"Normal copy completed: {source.name}")
                return True
            else:
                logging.error(
                    f"Executor failed to copy {source.name}: {copy_result.error_message}"
                )
                # The executor handles cleanup of partial/temp files
                return False

        except Exception as e:
            logging.error(
                f"Error in normal copy strategy for {source.name}: {e}", exc_info=True
            )
            return False

    async def _verify_file_integrity(self, source_path: str, dest_path: str) -> bool:
        """Verify that source and destination files are identical by size."""
        try:
            source_size = os.path.getsize(source_path)
            dest_size = os.path.getsize(dest_path)

            if source_size != dest_size:
                logging.error(f"Size mismatch: source={source_size}, dest={dest_size}")
                return False

            return True

        except Exception as e:
            logging.error(f"Error verifying file integrity: {e}")
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

    async def copy_file(
        self, source_path: str, dest_path: str, tracked_file: TrackedFile
    ) -> bool:
        """
        Copy a growing file with streaming approach.

        Monitors file growth and copies data while maintaining safety margin.
        """
        temp_dest_path = None

        try:
            # Check if file meets minimum size requirement before starting copy
            current_size = os.path.getsize(source_path)
            min_size_bytes = self.settings.growing_file_min_size_mb * 1024 * 1024

            if current_size < min_size_bytes:
                size_mb = current_size / (1024 * 1024)
                logging.info(
                    f"⏳ WAITING FOR SIZE: {os.path.basename(source_path)} "
                    f"({size_mb:.1f}MB < {self.settings.growing_file_min_size_mb}MB) - "
                    f"waiting for file to reach minimum size..."
                )

                # Wait for file to grow to minimum size
                while current_size < min_size_bytes:
                    await asyncio.sleep(
                        self.settings.growing_file_poll_interval_seconds
                    )

                    try:
                        current_size = os.path.getsize(source_path)
                        size_mb = current_size / (1024 * 1024)

                        logging.debug(
                            f"📏 SIZE CHECK: {os.path.basename(source_path)} "
                            f"current={size_mb:.1f}MB, target={self.settings.growing_file_min_size_mb}MB"
                        )
                    except OSError as e:
                        logging.error(f"Failed to check file size: {e}")
                        return False

                logging.info(
                    f"✅ SIZE REACHED: {os.path.basename(source_path)} "
                    f"({size_mb:.1f}MB >= {self.settings.growing_file_min_size_mb}MB) - starting copy"
                )

            logging.info(
                f"Starting growing copy: {os.path.basename(source_path)} "
                f"(rate: {tracked_file.growth_rate_mbps:.2f}MB/s)"
            )

            # Ensure destination directory exists (important for template system)
            dest_dir = Path(dest_path).parent
            dest_dir.mkdir(parents=True, exist_ok=True)
            logging.debug(f"Ensured destination directory exists: {dest_dir}")

            # Use temporary file if configured to do so
            if self.settings.use_temporary_file:
                temp_dest_path = create_temp_file_path(Path(dest_path))
                copy_dest_path = temp_dest_path
                logging.debug(
                    f"Using temporary file for growing copy: {temp_dest_path}"
                )
            else:
                copy_dest_path = dest_path
                logging.debug(f"Using direct growing copy to: {dest_path}")

            # Perform growing copy (status already set by FileCopyService)
            success = await self._copy_growing_file(
                source_path, copy_dest_path, tracked_file
            )

            if success:
                # Switch to normal copy mode for final data
                logging.info(
                    f"Growing copy phase complete. Finishing final part for: {os.path.basename(source_path)}"
                )

                # Switch to normal copy mode for final data - use existing tracked_file parameter
                await self.state_manager.update_file_status_by_id(
                    tracked_file.id, FileStatus.COPYING
                )

                # Finish copying any remaining data using the executor for consistency
                final_success = await self._finish_normal_copy(
                    source_path, str(copy_dest_path), tracked_file
                )

                if final_success:
                    # Verify and finalize
                    if await self._verify_file_integrity(
                        source_path, str(copy_dest_path)
                    ):
                        # If using temp file, rename it to final destination
                        if self.settings.use_temporary_file and temp_dest_path:
                            os.rename(temp_dest_path, dest_path)
                            logging.debug(
                                f"Renamed temp file to final destination: {dest_path}"
                            )

                        # Try to delete source file, but don't fail if it's locked
                        try:
                            os.remove(source_path)
                            logging.debug(
                                f"Source file deleted: {os.path.basename(source_path)}"
                            )
                        except (OSError, PermissionError) as e:
                            logging.warning(
                                f"Could not delete source file (may still be in use): {os.path.basename(source_path)} - {e}"
                            )
                            # This is OK for growing files that may still be open by the writer

                        # Update status to completed - use existing tracked_file parameter
                        await self.state_manager.update_file_status_by_id(
                            tracked_file.id,
                            FileStatus.COMPLETED,
                            copy_progress=100.0,
                            destination_path=dest_path,
                        )

                        logging.info(
                            f"Growing copy completed: {os.path.basename(source_path)}"
                        )
                        return True
                    else:
                        logging.error(
                            f"Growing copy verification failed: {source_path}"
                        )
                        return False
                else:
                    return False
            else:
                return False

        except Exception as e:
            logging.error(f"Error in growing copy strategy: {e}")
            return False
        finally:
            # Cleanup temporary file if it exists
            if temp_dest_path and os.path.exists(temp_dest_path):
                try:
                    os.remove(temp_dest_path)
                except Exception as e:
                    logging.warning(
                        f"Failed to cleanup temp file {temp_dest_path}: {e}"
                    )

    async def _copy_growing_file(
        self, source_path: str, dest_path: str, tracked_file: TrackedFile
    ) -> bool:
        """
        Copy growing file with safety margin.

        Continuously monitors file growth and copies data while staying behind write head.
        """
        try:
            chunk_size = (
                self.settings.growing_file_chunk_size_kb * 1024
            )  # Convert to bytes
            safety_margin_bytes = (
                self.settings.growing_file_safety_margin_mb * 1024 * 1024
            )
            poll_interval = self.settings.growing_file_poll_interval_seconds
            pause_ms = self.settings.growing_copy_pause_ms

            bytes_copied = 0
            last_file_size = 0
            no_growth_cycles = 0
            max_no_growth_cycles = (
                self.settings.growing_file_growth_timeout_seconds // poll_interval
            )

            # Open destination file for writing
            async with aiofiles.open(dest_path, "wb") as dst:
                while True:
                    # Get current file size
                    try:
                        current_file_size = os.path.getsize(source_path)
                    except OSError:
                        logging.warning(f"Cannot access source file: {source_path}")
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
                            logging.info(
                                f"File stopped growing: {os.path.basename(source_path)}"
                            )
                            break

                    # Calculate safe copy position (stay behind write head)
                    safe_copy_to = max(0, current_file_size - safety_margin_bytes)

                    if safe_copy_to > bytes_copied:
                        # Copy new data
                        bytes_to_copy = safe_copy_to - bytes_copied

                        async with aiofiles.open(source_path, "rb") as src:
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
                                copy_ratio = (
                                    (bytes_copied / current_file_size) * 100
                                    if current_file_size > 0
                                    else 0
                                )

                                # Calculate transfer rate using utility function
                                from datetime import datetime

                                current_time = datetime.now()
                                if not hasattr(self, "_copy_start_time"):
                                    self._copy_start_time = current_time
                                    self._copy_start_bytes = bytes_copied

                                elapsed_seconds = (
                                    current_time - self._copy_start_time
                                ).total_seconds()
                                transfer_rate = calculate_transfer_rate(
                                    bytes_copied - self._copy_start_bytes,
                                    elapsed_seconds,
                                )
                                copy_speed_mbps = transfer_rate / (
                                    1024 * 1024
                                )  # Convert to MB/s

                                # Standard update for alle copy modes - use existing tracked_file parameter - UUID precision
                                await self.state_manager.update_file_status_by_id(
                                    tracked_file.id,
                                    FileStatus.GROWING_COPY,
                                    copy_progress=copy_ratio,
                                    bytes_copied=bytes_copied,
                                    file_size=current_file_size,
                                    copy_speed_mbps=copy_speed_mbps,
                                )

                                # Throttle to avoid overwhelming disk I/O
                                if pause_ms > 0:
                                    await asyncio.sleep(pause_ms / 1000)
                    else:
                        # No new data to copy, but update progress - use existing tracked_file parameter
                        copy_ratio = (
                            (bytes_copied / current_file_size) * 100
                            if current_file_size > 0
                            else 0
                        )

                        await self.state_manager.update_file_status_by_id(
                            tracked_file.id,
                            FileStatus.GROWING_COPY,
                            copy_progress=copy_ratio,
                            bytes_copied=bytes_copied,
                            file_size=current_file_size,
                        )

                    # Wait before next growth check
                    await asyncio.sleep(poll_interval)

            return True

        except Exception as e:
            logging.error(f"Error in growing file copy: {e}")
            return False

    async def _finish_normal_copy(
        self, source_path: str, dest_path: str, tracked_file: TrackedFile
    ) -> bool:
        """Finish copying remaining data after growth stopped using FileCopyExecutor for the final chunk."""
        try:
            source = Path(source_path)
            dest = Path(dest_path)

            # Get final file size
            final_size = source.stat().st_size
            bytes_already_copied = dest.stat().st_size

            if bytes_already_copied >= final_size:
                logging.info(
                    f"No remaining data to copy for {source.name}. Finalizing."
                )
                return True

            logging.info(
                f"Finishing copy for {source.name}. Copied: {bytes_already_copied}, Total: {final_size}"
            )

            # This part is tricky. The executor is designed for full file copies.
            # We will use a manual approach here to append the rest of the data,
            # as refactoring the executor for partial copies is a larger task.

            # Use simple, optimal chunk size for the final copy
            chunk_size = self.settings.chunk_size_kb * 1024

            async with aiofiles.open(source, "rb") as src:
                async with aiofiles.open(dest, "ab") as dst:  # Append mode
                    await src.seek(bytes_already_copied)

                    while True:
                        chunk = await src.read(chunk_size)
                        if not chunk:
                            break

                        await dst.write(chunk)
                        bytes_already_copied += len(chunk)

                        # Update progress
                        progress = (
                            (bytes_already_copied / final_size) * 100
                            if final_size > 0
                            else 100
                        )

                        await self.state_manager.update_file_status_by_id(
                            tracked_file.id,
                            FileStatus.COPYING,
                            copy_progress=progress,
                            bytes_copied=bytes_already_copied,
                        )

            return True

        except Exception as e:
            logging.error(
                f"Error finishing normal copy for {source.name}: {e}", exc_info=True
            )
            return False

    async def _verify_file_integrity(self, source_path: str, dest_path: str) -> bool:
        """Verify that source and destination files are identical"""
        try:
            source_size = os.path.getsize(source_path)
            dest_size = os.path.getsize(dest_path)

            if source_size != dest_size:
                logging.error(f"Size mismatch: source={source_size}, dest={dest_size}")
                return False

            return True

        except Exception as e:
            logging.error(f"Error verifying file integrity: {e}")
            return False


class CopyStrategyFactory:
    """
    Factory for creating appropriate copy strategies.

    Determines which strategy to use based on file characteristics and settings.
    Supports both traditional and resumable copy strategies.
    """

    def __init__(
        self,
        settings: Settings,
        state_manager: StateManager,
        enable_resume: bool = True,
    ):
        self.settings = settings
        self.state_manager = state_manager
        self.enable_resume = enable_resume
        self.file_copy_executor = FileCopyExecutor(settings)

        # Initialize strategies
        if enable_resume:
            # Import resume strategies
            from app.utils.resumable_copy_strategies import (
                ResumableNormalFileCopyStrategy,
                ResumableGrowingFileCopyStrategy,
                CONSERVATIVE_CONFIG,
            )

            self.normal_strategy = ResumableNormalFileCopyStrategy(
                settings=settings,
                state_manager=state_manager,
                file_copy_executor=self.file_copy_executor,
                resume_config=CONSERVATIVE_CONFIG,
            )
            self.growing_strategy = ResumableGrowingFileCopyStrategy(
                settings=settings,
                state_manager=state_manager,
                file_copy_executor=self.file_copy_executor,
                resume_config=CONSERVATIVE_CONFIG,
            )
        else:
            # Traditional strategies
            self.normal_strategy = NormalFileCopyStrategy(
                settings, state_manager, self.file_copy_executor
            )
            self.growing_strategy = GrowingFileCopyStrategy(
                settings, state_manager, self.file_copy_executor
            )

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

        logger = logging.getLogger("app.services.copy_strategies")

        # Check if growing file support is enabled
        if self.settings.enable_growing_file_support:
            # Try growing strategy first
            supports_growing = self.growing_strategy.supports_file(tracked_file)
            logger.debug(
                f"Strategy selection for {tracked_file.file_path}: "
                f"is_growing_file={tracked_file.is_growing_file}, "
                f"status={tracked_file.status}, "
                f"supports_growing={supports_growing}"
            )

            if supports_growing:
                logger.info(
                    f"Selected GrowingFileCopyStrategy for {tracked_file.file_path}"
                )
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
