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
from app.services.state_manager import StateManager
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

                if not await self._verify_file_integrity(source_path, dest_path):
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

        except Exception as e:
            logging.error(
                f"Error in normal copy strategy for {source.name}: {e}", exc_info=True
            )
            return False

    async def _verify_file_integrity(self, source_path: str, dest_path: str) -> bool:
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

            dest_dir = Path(dest_path).parent
            dest_dir.mkdir(parents=True, exist_ok=True)
            logging.debug(f"Ensured destination directory exists: {dest_dir}")

            if self.settings.use_temporary_file:
                temp_dest_path = create_temp_file_path(Path(dest_path))
                copy_dest_path = temp_dest_path
                logging.debug(
                    f"Using temporary file for growing copy: {temp_dest_path}"
                )
            else:
                copy_dest_path = dest_path
                logging.debug(f"Using direct growing copy to: {dest_path}")

            success = await self._copy_growing_file(
                source_path, copy_dest_path, tracked_file
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

                if final_success:
                    if await self._verify_file_integrity(
                            source_path, str(copy_dest_path)
                    ):
                        if self.settings.use_temporary_file and temp_dest_path:
                            os.rename(temp_dest_path, dest_path)
                            logging.debug(
                                f"Renamed temp file to final destination: {dest_path}"
                            )

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

        except Exception as e:
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
            chunk_size = (
                    self.settings.growing_file_chunk_size_kb * 1024
            )
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

            async with aiofiles.open(dest_path, "wb") as dst:
                while True:
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
                    else:
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

            return True

        except Exception as e:
            logging.error(f"Error in growing file copy: {e}")
            return False

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

            async with aiofiles.open(source, "rb") as src:
                async with aiofiles.open(dest, "ab") as dst:
                    await src.seek(bytes_already_copied)

                    while True:
                        chunk = await src.read(chunk_size)
                        if not chunk:
                            break

                        await dst.write(chunk)
                        bytes_already_copied += len(chunk)

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
        except Exception as e:
            logging.error(
                f"Error finishing normal copy for {source.name}: {e}", exc_info=True
            )
            return False

    async def _verify_file_integrity(self, source_path: str, dest_path: str) -> bool:
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
