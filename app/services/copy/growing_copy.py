import asyncio
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import aiofiles
import aiofiles.os

from app.config import Settings
from app.core.events.event_bus import DomainEventBus
from app.core.events.file_events import FileCopyCompletedEvent
from app.core.file_repository import FileRepository
from app.core.file_state_machine import FileStateMachine
from app.core.exceptions import InvalidTransitionError
from app.models import FileStatus, TrackedFile
from app.services.copy.network_error_detector import NetworkErrorDetector, NetworkError
from app.services.copy.exceptions import FileCopyError, FileCopyTimeoutError, FileCopyIOError, FileCopyIntegrityError
from app.utils.progress_utils import calculate_transfer_rate
from app.core.events.file_events import FileCopyProgressEvent


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


class GrowingFileCopyStrategy():

    def __init__(
        self,
        settings: Settings,
        file_repository: FileRepository,
        event_bus: DomainEventBus,
        state_machine: FileStateMachine, # <-- TILFØJ DENNE
    ):
        self.settings = settings
        self.file_repository = file_repository
        self.event_bus = event_bus
        self._state_machine = state_machine # <-- TILFØJ DENNE


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
            except asyncio.TimeoutError as e:
                logging.error(f"File size check timed out for {source_path}")
                raise FileCopyTimeoutError(f"File size check timed out for {source_path}") from e
            except OSError as e:
                logging.error(f"Failed to access source file for size check: {e}")
                raise FileCopyIOError(f"Failed to access source file for size check {source_path}: {e}") from e

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
                    except asyncio.TimeoutError as e:
                        logging.error(f"File size check timed out for {source_path}")
                        raise FileCopyTimeoutError(f"File size check timed out for {source_path}") from e
                    except OSError as e:
                        logging.error(f"Failed to check file size: {e}")
                        raise FileCopyIOError(f"Failed to check file size {source_path}: {e}") from e

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

            dest_dir = Path(dest_path).parent
            try:
                await aiofiles.os.makedirs(dest_dir, exist_ok=True)
                logging.debug(f"Ensured destination directory exists: {dest_dir}")
            except Exception as e:
                logging.error(f"Directory creation failed for: {dest_dir}: {e}")
                raise FileCopyIOError(f"Directory creation failed for {dest_dir}: {e}") from e

            network_detector = NetworkErrorDetector()
            success = await self._copy_growing_file(
                source_path, dest_path, tracked_file, network_detector
            )

            if success:
                if await _verify_file_integrity(source_path, dest_path):
                    delete_success, delete_error = await self._delete_source_file_with_retry(source_path)
                    if not delete_success:
                        logging.warning(
                            f"Could not delete source file (may still be in use): {os.path.basename(source_path)} - {delete_error}"
                        )
                        # Use state machine for atomic transition
                        try:
                            await self._state_machine.transition(
                                file_id=tracked_file.id,
                                new_status=FileStatus.COMPLETED_DELETE_FAILED,
                                copy_progress=100.0,
                                destination_path=dest_path,
                                error_message=f"Could not delete source file: {delete_error}"
                            )
                        except (InvalidTransitionError, ValueError) as e:
                            logging.error(f"Kunne ikke sætte status til COMPLETED_DELETE_FAILED for {tracked_file.id}: {e}")
                        return True  # Still a success from a copy perspective

                    # Use state machine for atomic transition
                    try:
                        await self._state_machine.transition(
                            file_id=tracked_file.id,
                            new_status=FileStatus.COMPLETED,
                            copy_progress=100.0,
                            destination_path=dest_path,
                            error_message=None # Ryd fejl
                        )

                        # Publicer den domæne-specifikke event
                        if self.event_bus:
                            await self.event_bus.publish(
                                FileCopyCompletedEvent(
                                    file_id=tracked_file.id,
                                    file_path=tracked_file.file_path,
                                    destination_path=dest_path,
                                    bytes_copied=tracked_file.file_size
                                )
                            )

                        logging.info(f"Growing copy completed: {os.path.basename(source_path)}")
                        return True

                    except (InvalidTransitionError, ValueError) as e:
                        logging.error(f"Kunne ikke sætte status til COMPLETED for {tracked_file.id}: {e}")
                        raise FileCopyError(f"State transition til COMPLETED fejlede: {e}") from e
                else:
                    logging.error(f"Growing copy verification failed: {source_path}")
                    raise FileCopyIntegrityError(f"File integrity verification failed: {source_path}")
            else:
                raise FileCopyError(f"Copy execution failed unexpectedly for {source_path}")

        except FileNotFoundError:
            raise
        except NetworkError:
            raise
        except Exception as e:
            network_detector = NetworkErrorDetector()
            try:
                network_detector.check_write_error(e, "growing copy strategy")
            except NetworkError:
                logging.error(f"Network error detected in growing copy strategy: {e}")
                raise
            logging.error(f"Error in growing copy strategy: {e}")
            raise FileCopyError(f"Error in growing copy strategy: {e}") from e
        finally:
            if temp_dest_path and await aiofiles.os.path.exists(temp_dest_path):
                try:
                    await aiofiles.os.remove(temp_dest_path)
                except Exception as e:
                    logging.warning(
                        f"Failed to cleanup temp file {temp_dest_path}: {e}"
                    )

    async def _copy_growing_file(
        self, source_path: str, dest_path: str, tracked_file: TrackedFile, network_detector: NetworkErrorDetector
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

            async with aiofiles.open(dest_path, "wb") as dst:
                bytes_copied = await self._growing_copy_loop(
                    source_path,
                    dst,
                    tracked_file, # Pass the original tracked_file as initial_tracked_file
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
            try:
                network_detector.check_write_error(e, "growing file copy")
            except NetworkError:
                logging.error(f"Network error detected in growing file copy: {e}")
                raise
            logging.error(f"Error in growing file copy: {e}")
            raise FileCopyError(f"Error in growing file copy: {e}") from e

    async def _growing_copy_loop(
        self,
        source_path: str,
        dst,
        initial_tracked_file: TrackedFile, # Renamed parameter to avoid confusion
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
        last_progress_percent = -1  # Initialize with a value that ensures the first update is sent
        last_progress_update_time = datetime.now() - timedelta(seconds=1) # Initialize for immediate first update

        while True:
            # Brug 'initial_tracked_file' som reference, omdøb den til 'tracked_file'
            tracked_file = initial_tracked_file

            try:
                current_file_size = await aiofiles.os.path.getsize(source_path)
                print(f"Current file size: {current_file_size}")
            except asyncio.TimeoutError as e:
                logging.warning(f"File size check timed out for: {source_path}")
                raise FileCopyTimeoutError(f"File size check timed out for {source_path}") from e
            except OSError as e:
                logging.warning(f"Cannot access source file: {source_path}")
                raise FileCopyIOError(f"Cannot access source file {source_path}: {e}") from e
            except Exception as e:
                logging.error(f"Error checking file size: {e}")
                raise FileCopyError(f"Error checking file size for {source_path}: {e}") from e

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
                bytes_copied, last_progress_percent, last_progress_update_time = await self._copy_chunk_range(
                    source_path,
                    dst,
                    bytes_copied,
                    safe_copy_to,
                    chunk_size,
                    tracked_file, # Use tracked_file here
                    current_file_size,
                    pause_ms if use_pause else 0,
                    network_detector,
                    status,
                    last_progress_percent,
                    last_progress_update_time, # Pass the new variable
                )
            elif not file_finished_growing:
                # Vi lader _copy_chunk_range håndtere status-opdatering,
                # men vi skal stadig publicere progress, hvis vi venter.

                # Opdater kun, hvis det er nødvendigt (f.eks. > 1 sekund siden sidst)
                current_time = datetime.now()
                if (current_time - last_progress_update_time).total_seconds() >= 1.0:
                    # Send kun en progress-event, SÆT IKKE STATUS
                    if self.event_bus:
                        asyncio.create_task(self.event_bus.publish(FileCopyProgressEvent(
                            file_id=tracked_file.id,
                            bytes_copied=bytes_copied,
                            total_bytes=current_file_size,
                            copy_speed_mbps=0 # Vi venter
                        )))
                    last_progress_update_time = current_time # Opdater tiden

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
        last_progress_percent: int = -1,
        last_progress_update_time: datetime = None,
    ) -> tuple[int, int, datetime]:
        """
        Copy a range of bytes from source to destination with network error detection.
        Args:
            status: FileStatus to use for progress updates (GROWING_COPY or COPYING)
        Returns the final bytes copied count.
        """
        bytes_copied = start_bytes
        bytes_to_copy = end_bytes - start_bytes

        async with aiofiles.open(source_path, "rb") as src:
            # Anvend timeout på seek
            await asyncio.wait_for(
                src.seek(bytes_copied),
                timeout=self.settings.file_operation_timeout_seconds
            )
            while bytes_to_copy > 0:
                read_size = min(chunk_size, bytes_to_copy)
                chunk = await asyncio.wait_for(src.read(read_size), timeout=self.settings.file_operation_timeout_seconds)

                if not chunk:
                    break

                try:
                    await asyncio.wait_for(dst.write(chunk), timeout=self.settings.file_operation_timeout_seconds)
                except Exception as write_error:
                    network_detector.check_write_error(
                        write_error, "growing copy chunk write"
                    )
                    raise write_error

                chunk_len = len(chunk)
                bytes_copied += chunk_len
                bytes_to_copy -= chunk_len

                copy_ratio = (
                    (bytes_copied / current_file_size) * 100
                    if current_file_size > 0
                    else 0
                )

                progress_percent = int(copy_ratio)

                current_time = datetime.now()
                if (current_time - last_progress_update_time).total_seconds() >= 1.0:
                    if not hasattr(self, "_copy_start_time"):
                        self._copy_start_time = current_time
                        self._copy_start_bytes = bytes_copied

                    elapsed_seconds = (current_time - self._copy_start_time).total_seconds()
                    transfer_rate = calculate_transfer_rate(
                        bytes_copied - self._copy_start_bytes,
                        elapsed_seconds,
                    )
                    copy_speed_mbps = transfer_rate / (1024 * 1024)

                    # Publicer progress-event (som før)
                    if self.event_bus:
                        progress_event = FileCopyProgressEvent(
                            file_id=tracked_file.id,
                            bytes_copied=bytes_copied,
                            total_bytes=current_file_size,
                            copy_speed_mbps=copy_speed_mbps,
                        )
                        asyncio.create_task(self.event_bus.publish(progress_event))

                    last_progress_percent = progress_percent
                    last_progress_update_time = current_time

                    # Opdater status og metadata via StateMachine
                    try:
                        await self._state_machine.transition(
                            file_id=tracked_file.id,
                            new_status=status, # status er enten COPYING eller GROWING_COPY
                            # kwargs til at opdatere metadata:
                            copy_progress=copy_ratio,
                            bytes_copied=bytes_copied,
                            file_size=current_file_size,
                            copy_speed_mbps=copy_speed_mbps
                        )
                    except (InvalidTransitionError, ValueError) as e:
                        # Log, men lad være med at crashe kopieringen pga. en statusfejl
                        logging.warning(f"Kunne ikke opdatere progress-status for {tracked_file.id}: {e}")

                if pause_ms > 0:
                    await asyncio.sleep(pause_ms / 1000)

        return bytes_copied, last_progress_percent, last_progress_update_time

    async def _delete_source_file_with_retry(self, source_path: str) -> tuple[bool, str | None]:
        """
        Attempt to delete the source file with a few retries.
        Returns (success, error_message). error_message is None if successful.
        """
        last_error = None
        for i in range(3):
            try:
                await aiofiles.os.remove(source_path)
                logging.debug(f"Source file deleted: {os.path.basename(source_path)}")
                return True, None
            except Exception as e:
                last_error = str(e)
                logging.warning(
                    f"Delete attempt {i + 1}/3 failed for {os.path.basename(source_path)}: {e}"
                )
                if i < 2:
                    await asyncio.sleep(2)
        return False, last_error

    def _is_file_currently_growing(self, tracked_file: TrackedFile) -> bool:
        """
        Determine if a file is currently growing based on its status and growth history.

        Returns:
            True if file has a growing-related status, a positive growth rate,
            or has significantly increased in size since first seen.
            False otherwise.
        """
        # Primary check: status indicates active growth
        if tracked_file.status in [
            FileStatus.GROWING,
            FileStatus.READY_TO_START_GROWING,
            FileStatus.GROWING_COPY,
        ]:
            return True

        # Secondary check: if status is READY, but still has a growth rate or has grown significantly
        # This can happen if a file was growing, became stable, but then started growing again
        if tracked_file.status == FileStatus.READY:
            # Check for positive growth rate
            if tracked_file.growth_rate_mbps > 0:
                return True

            # Check for significant size increase since first seen (e.g., more than 10% or 1MB)
            if tracked_file.first_seen_size and tracked_file.file_size:
                size_increase = tracked_file.file_size - tracked_file.first_seen_size
                if size_increase > (tracked_file.first_seen_size * 0.1) or size_increase > (1 * 1024 * 1024): # 10% or 1MB
                    return True

        return False
