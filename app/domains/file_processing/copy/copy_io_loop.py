import asyncio
import logging
import os
import time

import aiofiles
from typing import Any

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

    def __init__(
        self,
        settings: Settings,
        state_machine: FileStateMachine,
        event_bus: DomainEventBus,
    ):
        self.settings = settings
        self._state_machine = state_machine
        self._event_bus = event_bus
        self._pending_tasks: set[asyncio.Task[None]] = set()

    async def _initial_seek(
        self,
        src,
        source_path: str,
        position: int,
        network_detector: NetworkErrorDetector,
    ) -> None:
        """Seek source file to starting position with timeout."""
        try:
            await asyncio.wait_for(
                src.seek(position),
                timeout=self.settings.file_operation_timeout_seconds
            )
        except asyncio.TimeoutError as e:
            logging.error(f"Timeout during file seek for {source_path} at position {position}")
            raise FileCopyTimeoutError(f"File seek timeout for {source_path}") from e
        except Exception as e:
            logging.error(f"Error during file seek for {source_path}: {type(e).__name__}: {e}", exc_info=True)
            network_detector.check_write_error(e, "file seek operation")
            raise

    async def _write_chunk_with_retry(
        self,
        src: Any,
        dst: Any,
        source_path: str,
        dest_path: str,
        bytes_copied: int,
        read_size: int,
        max_retries: int,
        network_detector: NetworkErrorDetector,
    ) -> tuple[bytes, Any, Any]:
        """
        Read a chunk from src and write to dst, with exponential-backoff retry.

        On each retry the stale src/dst handles are closed and reopened so that
        a brief SMB/NFS reconnect does not leave us retrying on a dead file
        descriptor.

        Returns (chunk, src, dst) on success — callers must use the returned
        handles because they may be fresh objects after a reopen.
        Raises FileCopyTimeoutError or NetworkError on persistent failure.
        Returns (b"", src, dst) on unexpected EOF.
        """
        chunk_retry_count = 0
        io_phase = "unknown"

        while True:
            try:
                # Re-seek before retry to ensure correct position
                if chunk_retry_count > 0:
                    # Close stale handles — a brief SMB/NFS reconnect leaves the
                    # OS-level file descriptors dead.  Reopening gives us fresh fds.
                    try:
                        await src.close()
                    except Exception:
                        pass
                    try:
                        await dst.close()
                    except Exception:
                        pass
                    src = await aiofiles.open(source_path, "rb")
                    dst = await aiofiles.open(dest_path, "r+b")
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
                    return b"", src, dst

                io_phase = "destination write"
                await asyncio.wait_for(
                    dst.write(chunk),
                    timeout=self.settings.file_operation_timeout_seconds
                )
                return chunk, src, dst

            except (asyncio.TimeoutError, OSError) as e:
                chunk_retry_count += 1
                is_timeout = isinstance(e, asyncio.TimeoutError)
                error_type = "Timeout" if is_timeout else type(e).__name__

                if chunk_retry_count >= max_retries:
                    if is_timeout:
                        logging.error(
                            f"Chunk {error_type} during {io_phase} at position {bytes_copied} for {source_path} "
                            f"after {max_retries} retries — giving up"
                        )
                        raise FileCopyTimeoutError(
                            f"Chunk I/O timeout during {io_phase} for {source_path} at position {bytes_copied}"
                        ) from e
                    else:
                        logging.error(
                            f"Chunk {error_type} during {io_phase} at position {bytes_copied} for {source_path}: "
                            f"{e} after {max_retries} retries"
                        )
                        network_detector.check_write_error(e, f"chunk {io_phase}")
                        raise

                wait_seconds = 2 ** chunk_retry_count  # exponential: 2s, 4s, 8s
                logging.warning(
                    f"⚠️ Chunk {error_type} during {io_phase} at position {bytes_copied} for "
                    f"{os.path.basename(source_path)} — retry {chunk_retry_count}/{max_retries} "
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

    async def _report_progress(
        self,
        tracked_file: TrackedFile,
        status: FileStatus,
        bytes_copied: int,
        current_file_size: int,
        copy_start_mono: float,
        copy_start_bytes: int,
    ) -> None:
        """Publish progress event and update state machine (called at most once per second)."""
        copy_ratio = (bytes_copied / current_file_size) * 100 if current_file_size > 0 else 0
        elapsed_seconds = time.monotonic() - copy_start_mono
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

        # BRUG STATEMACHINE TIL AT OPDATERE STATUS OG PROGRESS
        try:
            await self._state_machine.transition(
                file_id=tracked_file.id,
                new_status=status,  # (COPYING or GROWING_COPY)
                copy_progress=copy_ratio,
                bytes_copied=bytes_copied,
                file_size=current_file_size,
                copy_speed_mbps=copy_speed_mbps
            )
        except (InvalidTransitionError, ValueError) as e:
            logging.warning(f"Kunne ikke opdatere progress-status for {tracked_file.id}: {e}")
        except Exception as e:
            logging.warning(f"Unexpected error updating progress for {tracked_file.id}: {type(e).__name__}: {e}")

    async def copy_chunk_range(
        self,
        source_path: str,
        dst: Any,
        dest_path: str,
        start_bytes: int,
        end_bytes: int,
        chunk_size: int,
        tracked_file: TrackedFile,
        current_file_size: int,
        pause_ms: int,
        network_detector: NetworkErrorDetector,
        status: FileStatus,
        last_progress_percent: int,
        last_progress_mono: float,
    ) -> tuple[int, int, float, Any]:
        """
        Kopiér en række bytes fra kilde til destination med network error detection.

        Args:
            source_path: Sti til kildefil
            dst: Åben fil-handler til destination
            dest_path: Sti til destinationsfil (bruges til at genåbne ved retry)
            start_bytes: Start byte position
            end_bytes: Slut byte position
            chunk_size: Størrelse af chunks der læses ad gangen
            tracked_file: TrackedFile objekt for status opdateringer
            current_file_size: Aktuel fil størrelse
            pause_ms: Pause mellem chunks i millisekunder
            network_detector: Network error detector
            status: FileStatus til progress updates (GROWING_COPY eller COPYING)
            last_progress_percent: Sidste progress procent
            last_progress_mono: Monotonic timestamp for sidste progress opdatering

        Returns:
            Tuple af (bytes_copied, last_progress_percent, last_progress_mono, dst)
        """
        bytes_copied = start_bytes
        bytes_to_copy = end_bytes - start_bytes

        # Track timing per invocation (NOT on self — this is a shared instance)
        copy_start_mono = time.monotonic()
        copy_start_bytes = bytes_copied

        src = None
        try:
            src = await aiofiles.open(source_path, "rb")
            await self._initial_seek(src, source_path, bytes_copied, network_detector)

            # Defensive: ensure dst is at the correct position (with timeout)
            await self._initial_seek(dst, f"{source_path} (dst)", bytes_copied, network_detector)

            max_chunk_retries = self.settings.max_retry_attempts  # default: 3

            while bytes_to_copy > 0:
                read_size = min(chunk_size, bytes_to_copy)

                chunk, src, dst = await self._write_chunk_with_retry(
                    src, dst, source_path, dest_path, bytes_copied, read_size,
                    max_chunk_retries, network_detector,
                )

                if not chunk:
                    break  # EOF

                chunk_len = len(chunk)
                bytes_copied += chunk_len
                bytes_to_copy -= chunk_len

                # Opdater kun progress 1 gang i sekundet (som optimeret)
                now_mono = time.monotonic()
                if (now_mono - last_progress_mono) >= 1.0:
                    await self._report_progress(
                        tracked_file, status, bytes_copied,
                        current_file_size, copy_start_mono, copy_start_bytes,
                    )
                    copy_ratio = (bytes_copied / current_file_size) * 100 if current_file_size > 0 else 0
                    last_progress_percent = int(copy_ratio)
                    last_progress_mono = now_mono

                if pause_ms > 0:
                    try:
                        await asyncio.sleep(pause_ms / 1000)
                    except Exception as e:
                        logging.warning(f"Error during pause: {type(e).__name__}: {e}")

        except Exception as e:
            logging.error(f"Fatal error in copy_chunk_range for {source_path}: {type(e).__name__}: {e}", exc_info=True)
            # Re-raise so the calling code can handle it appropriately
            raise
        finally:
            if src is not None:
                try:
                    await src.close()
                except Exception:
                    pass

        return bytes_copied, last_progress_percent, last_progress_mono, dst