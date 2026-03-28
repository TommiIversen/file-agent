import asyncio
import logging
import os
from datetime import datetime

import aiofiles

from app.config import Settings
from app.core.events.event_bus import DomainEventBus
from app.core.events.file_events import FileCopyProgressEvent
from app.core.file_state_machine import FileStateMachine
from app.core.exceptions import InvalidTransitionError
from app.models import TrackedFile, FileStatus
from app.domains.file_processing.copy.network_error_detector import NetworkErrorDetector
from app.domains.file_processing.copy.exceptions import FileCopyTimeoutError


def calculate_transfer_rate(bytes_copied: int, elapsed_seconds: float) -> float:
    if elapsed_seconds <= 0:
        return 0.0

    return bytes_copied / elapsed_seconds


class CopyIoLoop:
    """
    Håndterer den rå, byte-for-byte I/O-loop for kopiering.
    Er ansvarlig for at kalde FileStateMachine for at opdatere progress.
    """

    _pending_tasks: set[asyncio.Task] = set()

    def __init__(
        self,
        settings: Settings,
        state_machine: FileStateMachine,
        event_bus: DomainEventBus,
    ):
        self.settings = settings
        self._state_machine = state_machine
        self._event_bus = event_bus

    async def copy_chunk_range(
        self,
        source_path: str,
        dst, # Dette er den åbne fil-handler
        start_bytes: int,
        end_bytes: int,
        chunk_size: int,
        tracked_file: TrackedFile,
        current_file_size: int,
        pause_ms: int,
        network_detector: NetworkErrorDetector,
        status: FileStatus,
        last_progress_percent: int,
        last_progress_update_time: datetime,
    ) -> tuple[int, int, datetime]:
        """
        Kopiér en række bytes fra kilde til destination med network error detection.
        
        Args:
            source_path: Sti til kildefil
            dst: Åben fil-handler til destination
            start_bytes: Start byte position
            end_bytes: Slut byte position
            chunk_size: Størrelse af chunks der læses ad gangen
            tracked_file: TrackedFile objekt for status opdateringer
            current_file_size: Aktuel fil størrelse
            pause_ms: Pause mellem chunks i millisekunder
            network_detector: Network error detector
            status: FileStatus til progress updates (GROWING_COPY eller COPYING)
            last_progress_percent: Sidste progress procent
            last_progress_update_time: Sidste gang progress blev opdateret
            
        Returns:
            Tuple af (bytes_copied, last_progress_percent, last_progress_update_time)
        """
        bytes_copied = start_bytes
        bytes_to_copy = end_bytes - start_bytes

        # Track timing per invocation (NOT on self — this is a shared instance)
        copy_start_time = datetime.now()
        copy_start_bytes = bytes_copied

        try:
            async with aiofiles.open(source_path, "rb") as src:
                try:
                    await asyncio.wait_for(
                        src.seek(bytes_copied),
                        timeout=self.settings.file_operation_timeout_seconds
                    )
                except asyncio.TimeoutError as e:
                    logging.error(f"Timeout during file seek for {source_path} at position {bytes_copied}")
                    raise FileCopyTimeoutError(f"File seek timeout for {source_path}") from e
                except Exception as e:
                    logging.error(f"Error during file seek for {source_path}: {type(e).__name__}: {e}", exc_info=True)
                    network_detector.check_write_error(e, "file seek operation")
                    raise

                max_chunk_retries = self.settings.max_retry_attempts  # default: 3

                while bytes_to_copy > 0:
                    chunk_retry_count = 0
                    chunk_written = False
                    io_phase = "unknown"  # Track which I/O operation we're in

                    while not chunk_written:
                        try:
                            read_size = min(chunk_size, bytes_to_copy)

                            # Re-seek before retry to ensure correct position
                            if chunk_retry_count > 0:
                                io_phase = "source seek"
                                await asyncio.wait_for(
                                    src.seek(bytes_copied),
                                    timeout=self.settings.file_operation_timeout_seconds
                                )
                                io_phase = "destination seek"
                                await asyncio.wait_for(
                                    dst.seek(bytes_copied),
                                    timeout=self.settings.file_operation_timeout_seconds
                                )

                            io_phase = "source read"
                            chunk = await asyncio.wait_for(
                                src.read(read_size), 
                                timeout=self.settings.file_operation_timeout_seconds
                            )
                            if not chunk:
                                logging.warning(f"Unexpected end of file while reading {source_path} at position {bytes_copied}")
                                bytes_to_copy = 0  # Force exit outer loop
                                chunk_written = True
                                break

                            io_phase = "destination write"
                            await asyncio.wait_for(
                                dst.write(chunk), 
                                timeout=self.settings.file_operation_timeout_seconds
                            )
                            chunk_written = True

                        except (asyncio.TimeoutError, OSError) as e:
                            chunk_retry_count += 1
                            is_timeout = isinstance(e, asyncio.TimeoutError)
                            error_type = "Timeout" if is_timeout else type(e).__name__

                            if chunk_retry_count >= max_chunk_retries:
                                if is_timeout:
                                    logging.error(
                                        f"Chunk {error_type} during {io_phase} at position {bytes_copied} for {source_path} "
                                        f"after {max_chunk_retries} retries — giving up"
                                    )
                                    raise FileCopyTimeoutError(
                                        f"Chunk I/O timeout during {io_phase} for {source_path} at position {bytes_copied}"
                                    ) from e
                                else:
                                    logging.error(
                                        f"Chunk {error_type} during {io_phase} at position {bytes_copied} for {source_path}: "
                                        f"{e} after {max_chunk_retries} retries"
                                    )
                                    network_detector.check_write_error(e, f"chunk {io_phase}")
                                    raise

                            wait_seconds = 2 ** chunk_retry_count  # exponential: 2s, 4s, 8s
                            logging.warning(
                                f"⚠️ Chunk {error_type} during {io_phase} at position {bytes_copied} for "
                                f"{os.path.basename(source_path)} — retry {chunk_retry_count}/{max_chunk_retries} "
                                f"in {wait_seconds}s"
                            )
                            await asyncio.sleep(wait_seconds)

                        except Exception as e:
                            logging.error(
                                f"Error during {io_phase} for {source_path} at position {bytes_copied}: "
                                f"{type(e).__name__}: {e}", exc_info=True
                            )
                            network_detector.check_write_error(e, f"chunk {io_phase}")
                            raise

                    chunk_len = len(chunk)
                    bytes_copied += chunk_len
                    bytes_to_copy -= chunk_len

                    copy_ratio = (bytes_copied / current_file_size) * 100 if current_file_size > 0 else 0
                    progress_percent = int(copy_ratio)
                    current_time = datetime.now()

                    # Opdater kun progress 1 gang i sekundet (som optimeret)
                    if (current_time - last_progress_update_time).total_seconds() >= 1.0:
                        elapsed_seconds = (current_time - copy_start_time).total_seconds()
                        transfer_rate = calculate_transfer_rate(
                            bytes_copied - copy_start_bytes,
                            elapsed_seconds,
                        )
                        copy_speed_mbps = transfer_rate / (1024 * 1024)

                        # Publicer "Fire and Forget" Progress Event
                        if self._event_bus:
                            try:
                                progress_event = FileCopyProgressEvent(
                                    file_id=tracked_file.id,
                                    bytes_copied=bytes_copied,
                                    total_bytes=current_file_size,
                                    copy_speed_mbps=copy_speed_mbps,
                                )
                                task = asyncio.create_task(self._event_bus.publish(progress_event))
                                self._pending_tasks.add(task)
                                task.add_done_callback(self._pending_tasks.discard)
                            except Exception as event_error:
                                logging.warning(f"Failed to publish progress event for {tracked_file.id}: {type(event_error).__name__}: {event_error}")
                        
                        last_progress_percent = progress_percent
                        last_progress_update_time = current_time

                        # BRUG STATEMACHINE TIL AT OPDATERE STATUS OG PROGRESS
                        try:
                            await self._state_machine.transition(
                                file_id=tracked_file.id,
                                new_status=status, # (COPYING or GROWING_COPY)
                                copy_progress=copy_ratio,
                                bytes_copied=bytes_copied,
                                file_size=current_file_size,
                                copy_speed_mbps=copy_speed_mbps
                            )
                        except (InvalidTransitionError, ValueError) as e:
                            logging.warning(f"Kunne ikke opdatere progress-status for {tracked_file.id}: {e}")
                        except Exception as e:
                            logging.warning(f"Unexpected error updating progress for {tracked_file.id}: {type(e).__name__}: {e}")

                    if pause_ms > 0:
                        try:
                            await asyncio.sleep(pause_ms / 1000)
                        except Exception as e:
                            logging.warning(f"Error during pause: {type(e).__name__}: {e}")

        except Exception as e:
            logging.error(f"Fatal error in copy_chunk_range for {source_path}: {type(e).__name__}: {e}", exc_info=True)
            # Re-raise so the calling code can handle it appropriately
            raise

        return bytes_copied, last_progress_percent, last_progress_update_time