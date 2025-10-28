import asyncio
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiofiles
import aiofiles.os

from app.config import Settings
from app.core.events.event_bus import DomainEventBus
from app.models import FileStatus, TrackedFile
from app.services.copy.file_copy_executor import FileCopyExecutor
from app.services.copy.network_error_detector import NetworkErrorDetector, NetworkError
from app.services.state_manager import StateManager
from app.utils.progress_utils import calculate_transfer_rate


async def _verify_file_integrity(source_path: str, dest_path: str) -> bool:
    try:
        source_size = await aiofiles.os.path.getsize(source_path)
        dest_size = await aiofiles.os.path.getsize(dest_path)

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
        event_bus: Optional[DomainEventBus] = None,
    ):
        self.settings = settings
        self.state_manager = state_manager
        self.file_copy_executor = file_copy_executor
        self._event_bus = event_bus

    @abstractmethod
    async def copy_file(
        self, source_path: str, dest_path: str, tracked_file: TrackedFile
    ) -> bool:
        pass

    @abstractmethod
    def supports_file(self, tracked_file: TrackedFile) -> bool:
        pass


class GrowingFileCopyStrategy(FileCopyStrategy):
    def supports_file(self, tracked_file: TrackedFile) -> bool:
        return True

    async def copy_file(
        self, source_path: str, dest_path: str, tracked_file: TrackedFile
    ) -> bool:
        temp_dest_path = None

        try:
            try:
                current_size = await asyncio.wait_for(
                    aiofiles.os.path.getsize(source_path),
                    timeout=1.0,  # 1 second timeout
                )
            except asyncio.TimeoutError:
                logging.error(f"File size check timed out for {source_path}")
                return False

            # Check if this is a growing file based on its status history
            is_growing_file = self._is_file_currently_growing(tracked_file)
            min_size_bytes = self.settings.growing_file_min_size_mb * 1024 * 1024

            # Only wait for minimum size if this is actually a growing file
            if is_growing_file and current_size < min_size_bytes:
                size_mb = current_size / (1024 * 1024)
                logging.info(
                    f"⏳ WAITING FOR SIZE: {os.path.basename(source_path)} "
                    f"({size_mb:.1f}MB < {self.settings.growing_file_min_size_mb}MB) - "
                    f"waiting for growing file to reach minimum size..."
                )

                while current_size < min_size_bytes:
                    await asyncio.sleep(
                        self.settings.growing_file_poll_interval_seconds
                    )

                    try:
                        current_size = await asyncio.wait_for(
                            aiofiles.os.path.getsize(source_path),
                            timeout=1.0,  # 1 second timeout
                        )
                        size_mb = current_size / (1024 * 1024)

                        logging.debug(
                            f"📏 SIZE CHECK: {os.path.basename(source_path)} "
                            f"current={size_mb:.1f}MB, target={self.settings.growing_file_min_size_mb}MB"
                        )
                    except asyncio.TimeoutError:
                        logging.error(f"File size check timed out for {source_path}")
                        return False
                    except OSError as e:
                        logging.error(f"Failed to check file size: {e}")
                        return False

                logging.info(
                    f"✅ SIZE REACHED: {os.path.basename(source_path)} "
                    f"({size_mb:.1f}MB >= {self.settings.growing_file_min_size_mb}MB) - starting copy"
                )
            elif not is_growing_file:
                size_mb = current_size / (1024 * 1024)
                logging.info(
                    f"📁 STATIC FILE: {os.path.basename(source_path)} "
                    f"({size_mb:.1f}MB) - starting immediate copy at full speed"
                )

            logging.info(
                f"Starting growing copy: {os.path.basename(source_path)} "
                f"(rate: {tracked_file.growth_rate_mbps:.2f}MB/s)"
            )

            latest_tracked_file = await self.state_manager.get_file_by_path(source_path)
            if latest_tracked_file:
                tracked_file = latest_tracked_file
                logging.debug(
                    f"🔄 Using latest tracked file UUID: {tracked_file.id[:8]}... for {os.path.basename(source_path)}"
                )
            else:
                logging.warning(
                    f"⚠️ Could not get latest tracked file for {source_path}, using provided reference: {tracked_file.id[:8]}..."
                )

            dest_dir = Path(dest_path).parent
            try:
                await aiofiles.os.makedirs(dest_dir, exist_ok=True)
                logging.debug(f"Ensured destination directory exists: {dest_dir}")
            except Exception as e:
                logging.error(f"Directory creation failed for: {dest_dir}: {e}")
                return False

            success = await self._copy_growing_file(
                source_path, dest_path, tracked_file
            )

            if success:
                if await _verify_file_integrity(source_path, dest_path):
                    try:
                        await aiofiles.os.remove(source_path)
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
                    logging.error(f"Growing copy verification failed: {source_path}")
                    return False
            else:
                return False

        except FileNotFoundError:
            raise
        except NetworkError:
            raise
        except Exception as e:
            error_str = str(e).lower()
            network_indicators = {
                "invalid argument",
                "errno 22",
                "network path was not found",
                "winerror 53",
                "the network name cannot be found",
                "winerror 67",
                "access is denied",
                "input/output error",
                "errno 5",
                "connection refused",
                "network is unreachable",
            }
            is_network_error = any(
                indicator in error_str for indicator in network_indicators
            )
            if hasattr(e, "errno") and e.errno in {22, 5, 53, 67, 1231, 13}:
                is_network_error = True
            if is_network_error:
                logging.error(f"Network error detected in growing copy strategy: {e}")
                raise NetworkError(f"Network error during growing copy: {e}")

            logging.error(f"Error in growing copy strategy: {e}")
            return False
        finally:
            if temp_dest_path and await aiofiles.os.path.exists(temp_dest_path):
                try:
                    await aiofiles.os.remove(temp_dest_path)
                except Exception as e:
                    logging.warning(
                        f"Failed to cleanup temp file {temp_dest_path}: {e}"
                    )

    async def _copy_growing_file(
        self, source_path: str, dest_path: str, tracked_file: TrackedFile
    ) -> bool:
        try:
            # Check if this is a static or growing file
            is_growing_file = self._is_file_currently_growing(tracked_file)

            chunk_size = self.settings.growing_file_chunk_size_kb * 1024
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

            if is_growing_file:
                logging.info(
                    f"🌱 GROWING COPY START: {os.path.basename(source_path)} "
                    f"starting growing file copy with safety margins"
                )
            else:
                logging.info(
                    f"⚡ STATIC COPY START: {os.path.basename(source_path)} "
                    f"starting full-speed static file copy"
                )
                # For static files, disable safety margins and delays for maximum speed
                safety_margin_bytes = 0
                pause_ms = 0
                no_growth_cycles = max_no_growth_cycles  # Skip growth detection

            network_detector = NetworkErrorDetector(
                destination_path=dest_path, check_interval_bytes=chunk_size * 10
            )

            async with aiofiles.open(dest_path, "wb") as dst:
                bytes_copied = await self._growing_copy_loop(
                    source_path,
                    dst,
                    tracked_file,
                    bytes_copied,
                    last_file_size,
                    no_growth_cycles,
                    max_no_growth_cycles,
                    safety_margin_bytes,
                    chunk_size,
                    poll_interval,
                    pause_ms,
                    network_detector,
                )

            return True

        except NetworkError:
            raise
        except Exception as e:
            error_str = str(e).lower()
            network_indicators = {
                "invalid argument",
                "errno 22",
                "network path was not found",
                "winerror 53",
                "the network name cannot be found",
                "winerror 67",
                "access is denied",
                "input/output error",
                "errno 5",
                "connection refused",
                "network is unreachable",
            }
            is_network_error = any(
                indicator in error_str for indicator in network_indicators
            )
            if hasattr(e, "errno") and e.errno in {22, 5, 53, 67, 1231, 13}:
                is_network_error = True
            if is_network_error:
                logging.error(f"Network error detected in growing copy: {e}")
                raise NetworkError(f"Network error during growing copy: {e}")

            logging.error(f"Error in growing file copy: {e}")
            return False

    async def _growing_copy_loop(
        self,
        source_path: str,
        dst,
        tracked_file: TrackedFile,
        bytes_copied: int,
        last_file_size: int,
        no_growth_cycles: int,
        max_no_growth_cycles: int,
        safety_margin_bytes: int,
        chunk_size: int,
        poll_interval: float,
        pause_ms: int,
        network_detector: NetworkErrorDetector,
    ) -> int:
        """
        Intelligent growing copy loop that adapts behavior based on file growth.
        Phase 1: Growing phase - uses safety margin and delays
        Phase 2: Finished growing - copies at full speed without delays/margin
        Returns the final bytes_copied count.
        """
        # Static files start as "finished growing" to skip safety margins
        file_finished_growing = no_growth_cycles >= max_no_growth_cycles

        while True:
            current_tracked_file = await self.state_manager.get_file_by_id(
                tracked_file.id
            )
            if not current_tracked_file:
                logging.warning(f"File disappeared during copy: {source_path}")
                return bytes_copied

            try:
                current_file_size = await asyncio.wait_for(
                    aiofiles.os.path.getsize(source_path), timeout=1.0
                )
            except asyncio.TimeoutError:
                logging.warning(f"File size check timed out for: {source_path}")
                break
            except OSError:
                logging.warning(f"Cannot access source file: {source_path}")
                break

            if not file_finished_growing:
                if current_file_size > last_file_size:
                    no_growth_cycles = 0
                    last_file_size = current_file_size
                else:
                    no_growth_cycles += 1

                    if no_growth_cycles >= max_no_growth_cycles:
                        logging.info(
                            f"🎯 GROWTH STOPPED: {os.path.basename(source_path)} - switching to full speed copy"
                        )
                        file_finished_growing = True

            if file_finished_growing:
                safe_copy_to = current_file_size
                status = FileStatus.COPYING
                use_pause = False
            else:
                safe_copy_to = max(0, current_file_size - safety_margin_bytes)
                status = FileStatus.GROWING_COPY

                distance_from_write_head = current_file_size - bytes_copied
                buffer_zone = safety_margin_bytes * 2

                if distance_from_write_head > buffer_zone:
                    use_pause = False
                    logging.debug(
                        f"🚀 FULL SPEED: {distance_from_write_head / 1024 / 1024:.1f}MB ahead of write head"
                    )
                else:
                    use_pause = True
                    logging.debug(
                        f"🐌 THROTTLED: Only {distance_from_write_head / 1024 / 1024:.1f}MB from write head"
                    )

            if safe_copy_to > bytes_copied:
                speed_mode = "🚀 FULL" if not use_pause else "🐌 THROTTLED"
                phase = "FINISH" if file_finished_growing else "GROWING"
                logging.debug(
                    f"{speed_mode} | {phase} | Copy {safe_copy_to - bytes_copied} bytes"
                )

                bytes_copied = await self._copy_chunk_range(
                    source_path,
                    dst,
                    bytes_copied,
                    safe_copy_to,
                    chunk_size,
                    tracked_file,
                    current_file_size,
                    pause_ms if use_pause else 0,
                    network_detector,
                    status,
                )
            elif not file_finished_growing:
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

            if file_finished_growing and bytes_copied >= current_file_size:
                logging.info(
                    f"✅ COPY COMPLETE: {os.path.basename(source_path)} ({bytes_copied} bytes)"
                )
                break

            if not file_finished_growing:
                await asyncio.sleep(poll_interval)

        return bytes_copied

    async def _copy_chunk_range(
        self,
        source_path: str,
        dst,
        start_bytes: int,
        end_bytes: int,
        chunk_size: int,
        tracked_file: TrackedFile,
        current_file_size: int,
        pause_ms: int,
        network_detector: NetworkErrorDetector,
        status: FileStatus = FileStatus.GROWING_COPY,
    ) -> int:
        """
        Copy a range of bytes from source to destination with network error detection.
        Args:
            status: FileStatus to use for progress updates (GROWING_COPY or COPYING)
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
                    network_detector.check_write_error(
                        write_error, "growing copy chunk write"
                    )
                    raise write_error

                chunk_len = len(chunk)
                bytes_copied += chunk_len
                bytes_to_copy -= chunk_len

                try:
                    await network_detector.check_destination_connectivity(bytes_copied)
                except NetworkError as ne:
                    logging.error(
                        f"Network connectivity lost during growing copy: {ne}"
                    )
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

                elapsed_seconds = (current_time - self._copy_start_time).total_seconds()
                transfer_rate = calculate_transfer_rate(
                    bytes_copied - self._copy_start_bytes,
                    elapsed_seconds,
                )
                copy_speed_mbps = transfer_rate / (1024 * 1024)

                if self._event_bus:
                    from app.core.events.file_events import FileCopyProgressEvent

                    progress_event = FileCopyProgressEvent(
                        file_id=tracked_file.id,
                        bytes_copied=bytes_copied,
                        total_bytes=current_file_size,
                        copy_speed_mbps=copy_speed_mbps,
                    )
                    asyncio.create_task(self._event_bus.publish(progress_event))

                await self.state_manager.update_file_status_by_id(
                    tracked_file.id,
                    status,
                    copy_progress=copy_ratio,
                    bytes_copied=bytes_copied,
                    file_size=current_file_size,
                    copy_speed_mbps=copy_speed_mbps,
                )

                if pause_ms > 0:
                    await asyncio.sleep(pause_ms / 1000)

        return bytes_copied

    def _is_file_currently_growing(self, tracked_file: TrackedFile) -> bool:
        """
        Determine if a file is currently growing based on its status.

        Returns:
            True if file has a growing-related status.
            False otherwise.
        """
        return tracked_file.status in [
            FileStatus.GROWING,
            FileStatus.READY_TO_START_GROWING,
            FileStatus.GROWING_COPY,
        ]
