import asyncio
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Dict

import aiofiles

from app.config import Settings
from app.models import FileStatus, TrackedFile
from app.services.copy.file_copy_executor import FileCopyExecutor, CopyProgress
from app.services.copy.network_error_detector import NetworkErrorDetector, NetworkError
from app.services.state_manager import StateManager
from app.utils.progress_utils import calculate_transfer_rate


async def _verify_file_integrity(source_path: str, dest_path: str) -> bool:
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
        pass

    @abstractmethod
    def supports_file(self, tracked_file: TrackedFile) -> bool:
        pass


class NormalFileCopyStrategy(FileCopyStrategy):

    def supports_file(self, tracked_file: TrackedFile) -> bool:
        return not tracked_file.is_growing_file

    async def copy_file(
            self, source_path: str, dest_path: str, tracked_file: TrackedFile
    ) -> bool:
        source = Path(source_path)
        dest = Path(dest_path)

        try:
            logging.info(f"Starting normal copy via executor: {source.name}")

            await self.state_manager.update_file_status_by_id(
                tracked_file.id, FileStatus.COPYING, copy_progress=0.0
            )

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

            copy_result = await self.file_copy_executor.copy_file(
                source=source, dest=dest, progress_callback=progress_callback
            )

            if copy_result.success:
                logging.info(
                    f"Executor finished successfully for {source.name}. Verifying and finalizing."
                )

                if not await _verify_file_integrity(source_path, dest_path):
                    logging.error(f"Post-copy verification failed for {source.name}")
                    return False

                try:
                    os.remove(source_path)
                    logging.debug(f"Source file deleted: {source.name}")
                except (OSError, PermissionError) as e:
                    logging.warning(
                        f"Could not delete source file (may still be in use): {source.name} - {e}"
                    )

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
                return False

        except NetworkError:
            # Re-raise network errors for immediate failure handling
            raise
        except Exception as e:
            logging.error(
                f"Error in normal copy strategy for {source.name}: {e}", exc_info=True
            )
            return False



class GrowingFileCopyStrategy(FileCopyStrategy):

    def supports_file(self, tracked_file: TrackedFile) -> bool:
        return tracked_file.is_growing_file

    async def copy_file(
            self, source_path: str, dest_path: str, tracked_file: TrackedFile
    ) -> bool:
        temp_dest_path = None

        try:
            current_size = os.path.getsize(source_path)
            min_size_bytes = self.settings.growing_file_min_size_mb * 1024 * 1024

            if current_size < min_size_bytes:
                size_mb = current_size / (1024 * 1024)
                logging.info(
                    f"⏳ WAITING FOR SIZE: {os.path.basename(source_path)} "
                    f"({size_mb:.1f}MB < {self.settings.growing_file_min_size_mb}MB) - "
                    f"waiting for file to reach minimum size..."
                )

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
            
            # CRITICAL: Ensure we have the latest tracked file reference from state manager
            # to avoid UUID mismatches in resume scenarios
            latest_tracked_file = await self.state_manager.get_file_by_path(source_path)
            if latest_tracked_file:
                tracked_file = latest_tracked_file
                logging.debug(f"🔄 Using latest tracked file UUID: {tracked_file.id[:8]}... for {os.path.basename(source_path)}")
            else:
                logging.warning(f"⚠️ Could not get latest tracked file for {source_path}, using provided reference: {tracked_file.id[:8]}...")

            dest_dir = Path(dest_path).parent
            dest_dir.mkdir(parents=True, exist_ok=True)
            logging.debug(f"Ensured destination directory exists: {dest_dir}")

            copy_dest_path = dest_path

            success = await self._copy_growing_file(
                source_path, dest_path, tracked_file
            )

            if success:
                logging.info(
                    f"Growing copy phase complete. Finishing final part for: {os.path.basename(source_path)}"
                )

                await self.state_manager.update_file_status_by_id(
                    tracked_file.id, FileStatus.COPYING
                )

                try:
                    final_success = await self._finish_normal_copy(
                        source_path, str(copy_dest_path), tracked_file
                    )
                except FileNotFoundError:
                    # Source file disappeared during copying - let this bubble up
                    # so error classifier can properly handle it as REMOVED
                    raise
                except NetworkError:
                    # Network error during finish phase - let this bubble up for immediate failure
                    raise

                if final_success:
                    if await _verify_file_integrity(
                            source_path, str(copy_dest_path)
                    ):
                        try:
                            os.remove(source_path)
                            logging.debug(
                                f"Source file deleted: {os.path.basename(source_path)}"
                            )
                        except (OSError, PermissionError) as e:
                            logging.warning(
                                f"Could not delete source file (may still be in use): {os.path.basename(source_path)} - {e}"
                            )

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

        except FileNotFoundError:
            # Source file disappeared during copying - let this bubble up to error classifier
            raise
        except NetworkError:
            # Network error during copy - let this bubble up for immediate failure
            raise
        except Exception as e:
            # Check if this exception might be network-related before giving up
            error_str = str(e).lower()
            
            # Check for network error patterns in the exception
            network_indicators = {
                "invalid argument", "errno 22", "network path was not found", "winerror 53",
                "the network name cannot be found", "winerror 67", "access is denied",
                "input/output error", "errno 5", "connection refused", "network is unreachable"
            }
            
            is_network_error = any(indicator in error_str for indicator in network_indicators)
            
            # Check errno if available
            if hasattr(e, "errno") and e.errno in {22, 5, 53, 67, 1231, 13}:
                is_network_error = True
                
            if is_network_error:
                logging.error(f"Network error detected in growing copy strategy: {e}")
                raise NetworkError(f"Network error during growing copy: {e}")
            
            logging.error(f"Error in growing copy strategy: {e}")
            return False
        finally:
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
        try:
            chunk_size = self.settings.growing_file_chunk_size_kb * 1024
            safety_margin_bytes = self.settings.growing_file_safety_margin_mb * 1024 * 1024
            poll_interval = self.settings.growing_file_poll_interval_seconds
            pause_ms = self.settings.growing_copy_pause_ms

            bytes_copied = 0
            last_file_size = 0
            no_growth_cycles = 0
            max_no_growth_cycles = self.settings.growing_file_growth_timeout_seconds // poll_interval

            # CRITICAL: Resume from existing progress if destination file exists
            dest_file_path = Path(dest_path)

            logging.info(
                f"🚀 GROWING COPY START: {os.path.basename(source_path)} "
                f"starting fresh copy"
            )

            # Initialize network error detector for fail-fast behavior
            network_detector = NetworkErrorDetector(
                destination_path=dest_path,
                check_interval_bytes=chunk_size * 10  # Check every 10 chunks
            )
            
            async with aiofiles.open(dest_path, "wb") as dst:
                bytes_copied = await self._growing_copy_loop(
                    source_path, dst, tracked_file, bytes_copied, last_file_size,
                    no_growth_cycles, max_no_growth_cycles, safety_margin_bytes,
                    chunk_size, poll_interval, pause_ms, network_detector
                )

            return True

        except NetworkError:
            # Re-raise network errors for immediate failure handling
            raise
        except Exception as e:
            # Check if this exception might be network-related before giving up
            error_str = str(e).lower()
            
            # Check for network error patterns in the exception
            network_indicators = {
                "invalid argument", "errno 22", "network path was not found", "winerror 53",
                "the network name cannot be found", "winerror 67", "access is denied",
                "input/output error", "errno 5", "connection refused", "network is unreachable"
            }
            
            is_network_error = any(indicator in error_str for indicator in network_indicators)
            
            # Check errno if available
            if hasattr(e, "errno") and e.errno in {22, 5, 53, 67, 1231, 13}:
                is_network_error = True
                
            if is_network_error:
                logging.error(f"Network error detected in growing copy: {e}")
                raise NetworkError(f"Network error during growing copy: {e}")
            
            logging.error(f"Error in growing file copy: {e}")
            return False

    async def _growing_copy_loop(
            self, source_path: str, dst, tracked_file: TrackedFile, 
            bytes_copied: int, last_file_size: int, no_growth_cycles: int,
            max_no_growth_cycles: int, safety_margin_bytes: int, chunk_size: int,
            poll_interval: float, pause_ms: int, network_detector: NetworkErrorDetector
    ) -> int:
        """
        Main growing copy loop extracted for better testability.
        Returns the final bytes_copied count.
        """
        while True:
            # NOTE: Pause detection removed in fail-and-rediscover strategy
            # Files now fail immediately instead of pausing during network issues
            
            current_tracked_file = await self.state_manager.get_file_by_id(tracked_file.id)
            if not current_tracked_file:
                logging.warning(f"File disappeared during copy: {source_path}")
                return bytes_copied

            try:
                current_file_size = os.path.getsize(source_path)
            except OSError:
                logging.warning(f"Cannot access source file: {source_path}")
                break

            if current_file_size > last_file_size:
                no_growth_cycles = 0
                last_file_size = current_file_size
            else:
                no_growth_cycles += 1

                if no_growth_cycles >= max_no_growth_cycles:
                    logging.info(
                        f"File stopped growing: {os.path.basename(source_path)}"
                    )
                    break

            safe_copy_to = max(0, current_file_size - safety_margin_bytes)

            if safe_copy_to > bytes_copied:
                bytes_copied = await self._copy_chunk_range(
                    source_path, dst, bytes_copied, safe_copy_to, chunk_size,
                    tracked_file, current_file_size, pause_ms, network_detector
                )
            else:
                # No new data to copy, just update progress
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

            await asyncio.sleep(poll_interval)

        return bytes_copied

    async def _copy_chunk_range(
            self, source_path: str, dst, start_bytes: int, end_bytes: int, 
            chunk_size: int, tracked_file: TrackedFile, current_file_size: int,
            pause_ms: int, network_detector: NetworkErrorDetector
    ) -> int:
        """
        Copy a range of bytes from source to destination with network error detection.
        Returns the final bytes copied count.
        """
        bytes_copied = start_bytes
        bytes_to_copy = end_bytes - start_bytes

        async with aiofiles.open(source_path, "rb") as src:
            await src.seek(bytes_copied)

            while bytes_to_copy > 0:
                read_size = min(chunk_size, bytes_to_copy)
                chunk = await src.read(read_size)

                if not chunk:
                    break

                try:
                    await dst.write(chunk)
                except Exception as write_error:
                    # Check if write error is network-related for immediate failure
                    network_detector.check_write_error(write_error, "growing copy chunk write")
                    # If not network error, re-raise original error
                    raise write_error
                    
                chunk_len = len(chunk)
                bytes_copied += chunk_len
                bytes_to_copy -= chunk_len

                # Check network connectivity periodically for fail-fast behavior
                try:
                    network_detector.check_destination_connectivity(bytes_copied)
                except NetworkError as ne:
                    logging.error(f"Network connectivity lost during growing copy: {ne}")
                    raise ne

                copy_ratio = (
                    (bytes_copied / current_file_size) * 100
                    if current_file_size > 0
                    else 0
                )

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
                )

                await self.state_manager.update_file_status_by_id(
                    tracked_file.id,
                    FileStatus.GROWING_COPY,
                    copy_progress=copy_ratio,
                    bytes_copied=bytes_copied,
                    file_size=current_file_size,
                    copy_speed_mbps=copy_speed_mbps,
                )

                if pause_ms > 0:
                    await asyncio.sleep(pause_ms / 1000)

        return bytes_copied

    async def _finish_normal_copy(
            self, source_path: str, dest_path: str, tracked_file: TrackedFile
    ) -> bool:
        try:
            source = Path(source_path)
            dest = Path(dest_path)

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

            chunk_size = self.settings.chunk_size_kb * 1024

            # Initialize network error detector for finish phase
            network_detector = NetworkErrorDetector(
                destination_path=dest_path,
                check_interval_bytes=chunk_size * 5  # Check every 5 chunks
            )

            async with aiofiles.open(source, "rb") as src:
                async with aiofiles.open(dest, "ab") as dst:
                    await src.seek(bytes_already_copied)

                    while True:
                        chunk = await src.read(chunk_size)
                        if not chunk:
                            break

                        try:
                            await dst.write(chunk)
                        except Exception as write_error:
                            # Check if write error is network-related
                            network_detector.check_write_error(write_error, "finish copy chunk write")
                            # If not network error, re-raise original error
                            raise write_error
                            
                        bytes_already_copied += len(chunk)

                        # Check network connectivity periodically
                        try:
                            network_detector.check_destination_connectivity(bytes_already_copied)
                        except NetworkError as ne:
                            logging.error(f"Network connectivity lost during finish copy: {ne}")
                            raise ne

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

        except FileNotFoundError as e:
            # Source file disappeared during copying - re-raise so error classifier can handle it
            logging.error(
                f"Source file no longer exists while finishing copy for {source.name}: {e}"
            )
            raise e
        except NetworkError:
            # Re-raise network errors for immediate failure handling
            raise
        except Exception as e:
            logging.error(
                f"Error finishing normal copy for {source.name}: {e}", exc_info=True
            )
            return False


class CopyStrategyFactory:

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

        if enable_resume:
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
            self.normal_strategy = NormalFileCopyStrategy(
                settings, state_manager, self.file_copy_executor
            )
            self.growing_strategy = GrowingFileCopyStrategy(
                settings, state_manager, self.file_copy_executor
            )

    def get_strategy(self, tracked_file: TrackedFile) -> FileCopyStrategy:
        import logging

        logger = logging.getLogger("app.services.copy_strategies")

        if self.settings.enable_growing_file_support:
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

        logger.info(f"Selected NormalFileCopyStrategy for {tracked_file.file_path}")
        return self.normal_strategy

    def get_available_strategies(self) -> Dict[str, FileCopyStrategy]:
        strategies = {"normal": self.normal_strategy}

        if self.settings.enable_growing_file_support:
            strategies["growing"] = self.growing_strategy

        return strategies
