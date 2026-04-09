import asyncio
import logging
import os
import time
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
from app.domains.file_processing.copy.network_error_detector import NetworkErrorDetector, NetworkError
from app.domains.file_processing.copy.exceptions import FileCopyError, FileCopyTimeoutError, FileCopyIOError, FileCopyIntegrityError
from app.domains.file_processing.copy.file_verification import FileVerificationService
from app.domains.file_processing.copy.copy_io_loop import CopyIoLoop
from app.core.events.file_events import FileCopyProgressEvent
from app.utils.file_operations import generate_conflict_free_path


class GrowingFileCopyStrategy():

    def __init__(
        self,
        settings: Settings,
        file_repository: FileRepository,
        event_bus: DomainEventBus,
        state_machine: FileStateMachine, # <-- NY
        verification_service: FileVerificationService, # <-- NY
        io_loop: CopyIoLoop, # <-- NY
    ):
        self.settings = settings
        self.file_repository = file_repository
        self._event_bus = event_bus # Fix: Use _event_bus (with underscore) for consistency
        self._state_machine = state_machine
        self._verification_service = verification_service
        self._io_loop = io_loop
        self._pending_tasks: set[asyncio.Task[None]] = set()


    def supports_file(self, tracked_file: TrackedFile) -> bool:
        return True

    async def _get_file_size(self, path: str) -> int:
        """Get file size with timeout protection."""
        try:
            return await asyncio.wait_for(
                aiofiles.os.path.getsize(path),
                timeout=1.0,
            )
        except asyncio.TimeoutError as e:
            logging.error(f"File size check timed out for {path}")
            raise FileCopyTimeoutError(f"File size check timed out for {path}") from e
        except OSError as e:
            logging.error(f"Failed to access file for size check: {e}", exc_info=True)
            raise FileCopyIOError(f"Failed to access file for size check {path}: {e}") from e

    async def copy_file(
        self, source_path: str, dest_path: str, tracked_file: TrackedFile
    ) -> bool:
        network_detector = NetworkErrorDetector(
            event_bus=self._event_bus,
            current_file_id=tracked_file.id
        )

        try:
            current_size = await self._get_file_size(source_path)

            # Check if this is a growing file based on its status history
            is_growing_file = self.is_file_currently_growing(tracked_file)
            min_size_bytes = self.settings.growing_file_min_size_mb * 1024 * 1024

            # Only wait for minimum size if this is actually a growing file AND it's not already approved to start
            # Files with READY_TO_START_GROWING have already been size-checked by the growing file detector
            if is_growing_file and current_size < min_size_bytes:
                size_mb = current_size / (1024 * 1024)
                logging.info(
                    f" WAITING FOR SIZE: {os.path.basename(source_path)} "
                    f"({size_mb:.1f}MB < {self.settings.growing_file_min_size_mb}MB) - "
                    f"waiting for growing file to reach minimum size..."
                )

                while current_size < min_size_bytes:
                    await asyncio.sleep(
                        self.settings.growing_file_poll_interval_seconds
                    )

                    current_size = await self._get_file_size(source_path)
                    size_mb = current_size / (1024 * 1024)

                    logging.debug(
                        f" SIZE CHECK: {os.path.basename(source_path)} "
                        f"current={size_mb:.1f}MB, target={self.settings.growing_file_min_size_mb}MB"
                    )

                logging.info(
                    f" SIZE REACHED: {os.path.basename(source_path)} "
                    f"({size_mb:.1f}MB >= {self.settings.growing_file_min_size_mb}MB) - starting copy"
                )
            elif not is_growing_file:
                size_mb = current_size / (1024 * 1024)
                logging.info(
                    f" STATIC FILE: {os.path.basename(source_path)} "
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
                logging.error(f"Directory creation failed for: {dest_dir}: {e}", exc_info=True)
                raise FileCopyIOError(f"Directory creation failed for {dest_dir}: {e}") from e

            # Pre-copy overwrite protection: re-check destination right before copy
            # to prevent TOCTOU race where another copy or Justin flip created a file
            # at dest_path between preparation and execution
            resolved_dest = str(await generate_conflict_free_path(Path(dest_path)))
            if resolved_dest != dest_path:
                logging.warning(
                    f"⚠️ CONFLICT DETECTED before copy: {os.path.basename(dest_path)} already exists. "
                    f"Using: {os.path.basename(resolved_dest)}"
                )
                dest_path = resolved_dest

            success = await self._copy_growing_file(
                source_path, dest_path, tracked_file, network_detector
            )

            if success:
                verification_success, source_bytes, dest_bytes = await self._verification_service.verify_integrity(source_path, dest_path)
                if verification_success:
                    # For growing files bruger vi destination størrelsen som det faktiske antal bytes kopieret
                    actual_bytes_copied = dest_bytes

                    # Gate 2: Defense-in-depth — NEVER delete source unless sizes match exactly
                    if source_bytes != dest_bytes:
                        logging.error(
                            f"SAFETY GATE: Refusing to delete source — size mismatch "
                            f"(source={source_bytes}, dest={dest_bytes}): {os.path.basename(source_path)}"
                        )
                        raise FileCopyIntegrityError(
                            f"Source/dest size mismatch after verification: "
                            f"source={source_bytes}, dest={dest_bytes}"
                        )

                    delete_success, delete_error = await self._verification_service.delete_source_file(source_path)
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
                                bytes_copied=actual_bytes_copied, # Opdater med faktiske bytes
                                file_size=actual_bytes_copied, # Opdater file_size til den faktiske størrelse
                                error_message=f"Could not delete source file: {delete_error}"
                            )
                        except (InvalidTransitionError, ValueError) as e:
                            logging.error(f"Kunne ikke sætte status til COMPLETED_DELETE_FAILED for {tracked_file.id}: {e}", exc_info=True)
                        return True # Still a success from a copy perspective

                    # Use state machine for atomic transition
                    try:
                        await self._state_machine.transition(
                            file_id=tracked_file.id,
                            new_status=FileStatus.COMPLETED,
                            copy_progress=100.0,
                            destination_path=dest_path,
                            bytes_copied=actual_bytes_copied, # Opdater med faktiske bytes
                            file_size=actual_bytes_copied, # Opdater file_size til den faktiske størrelse
                            error_message=None # Ryd fejl
                        )

                        # Publicer den domæne-specifikke event med rigtige bytes
                        if self._event_bus:
                            await self._event_bus.publish(
                                FileCopyCompletedEvent(
                                    file_id=tracked_file.id,
                                    file_path=tracked_file.file_path,
                                    destination_path=dest_path,
                                    bytes_copied=actual_bytes_copied, # Brug faktiske kopierede bytes
                                    source_size=source_bytes, # Tilføj source størrelse
                                    dest_size=dest_bytes       # Tilføj destination størrelse
                                )
                            )

                        logging.info(f"Growing copy completed: {os.path.basename(source_path)}")
                        return True

                    except (InvalidTransitionError, ValueError) as e:
                        logging.error(f"Kunne ikke sætte status til COMPLETED for {tracked_file.id}: {e}", exc_info=True)
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
        except FileCopyError:
            # Already a copy error — don't wrap again (avoids FileCopyError: FileCopyError: ...)
            raise
        except Exception as e:
            try:
                network_detector.check_write_error(e, "growing copy strategy")
            except NetworkError:
                raise
            logging.error(f"Error in growing copy strategy for {source_path}: {type(e).__name__}: {e}", exc_info=True)
            raise FileCopyError(f"Error in growing copy strategy: {type(e).__name__}: {e}") from e
        finally:
            # We intentionally do NOT delete partial destination files on failure.
            # A partial copy (e.g. 6GB of 20GB) is better than no data at all.
            # The pre-copy conflict check + _copy1 suffix ensures retries won't
            # overwrite the partial file — they get a new name instead.
            if dest_path:
                logging.debug(f"Copy finished for {os.path.basename(source_path)} → {os.path.basename(dest_path)}")

    async def _copy_growing_file(
        self, source_path: str, dest_path: str, tracked_file: TrackedFile, network_detector: NetworkErrorDetector
    ) -> bool:
        try:
            # Check if this is a static or growing file
            is_growing_file = self.is_file_currently_growing(tracked_file)

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
                    f" GROWING COPY START: {os.path.basename(source_path)} "
                    f"starting growing file copy with safety margins"
                )
            else:
                logging.info(
                    f" STATIC COPY START: {os.path.basename(source_path)} "
                    f"starting full-speed static file copy"
                )
                # For static files, disable safety margins and delays for maximum speed
                safety_margin_bytes = 0
                pause_ms = 0
                no_growth_cycles = max_no_growth_cycles # Skip growth detection

            # Open destination file explicitly (not via `async with`) so that
            # a transient OSError during close (e.g. Errno 9 Bad file descriptor
            # on SMB/NFS) does not get misclassified as a network error after all
            # data has already been written and flushed successfully.
            dst = await aiofiles.open(dest_path, "wb")
            try:
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

                # Flush to ensure all data is written to the network destination
                # before we close the file handle and verify integrity
                try:
                    await dst.flush()
                except Exception as flush_err:
                    logging.warning(f"Flush failed for {os.path.basename(dest_path)}: {flush_err}")
            finally:
                # Close the file handle separately — a Bad file descriptor here
                # does NOT mean the copy failed (data was already flushed).
                try:
                    await dst.close()
                except OSError as close_err:
                    logging.warning(
                        f"Non-fatal error closing destination file handle for "
                        f"{os.path.basename(dest_path)}: {close_err} — "
                        f"data was already flushed, continuing with verification"
                    )

            return True

        except NetworkError:
            raise
        except Exception as e:
            try:
                network_detector.check_write_error(e, "growing file copy")
            except NetworkError:
                logging.error(f"Network error detected in growing file copy for {source_path}: {e}", exc_info=True)
                raise
            logging.error(f"Error in growing file copy for {source_path}: {type(e).__name__}: {e}", exc_info=True)
            raise FileCopyError(f"Error in growing file copy: {type(e).__name__}: {e}") from e

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
        last_progress_percent = -1 # Initialize with a value that ensures the first update is sent
        last_progress_mono = time.monotonic() - 1.0 # Initialize for immediate first update

        while True:
            # Brug 'initial_tracked_file' som reference, omdøb den til 'tracked_file'
            tracked_file = initial_tracked_file

            current_file_size = await self._get_file_size(source_path)
            logging.debug(f"Current file size: {current_file_size}")

            if not file_finished_growing:
                if current_file_size > last_file_size:
                    no_growth_cycles = 0
                    last_file_size = current_file_size
                else:
                    no_growth_cycles += 1

                    if no_growth_cycles >= max_no_growth_cycles:
                        logging.info(
                            f" GROWTH STOPPED: {os.path.basename(source_path)} - switching to full speed copy"
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
                        f" FULL SPEED: {distance_from_write_head / 1024 / 1024:.1f}MB ahead of write head"
                    )
                else:
                    use_pause = True
                    logging.debug(
                        f" THROTTLED: Only {distance_from_write_head / 1024 / 1024:.1f}MB from write head"
                    )

            if safe_copy_to > bytes_copied:
                bytes_copied, last_progress_percent, last_progress_mono = await self._io_loop.copy_chunk_range(
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
                    last_progress_mono,
                )
            elif not file_finished_growing:
                # Vi lader _copy_chunk_range håndtere status-opdatering,
                # men vi skal stadig publicere progress, hvis vi venter.

                # Opdater kun, hvis det er nødvendigt (f.eks. > 1 sekund siden sidst)
                current_mono = time.monotonic()
                if (current_mono - last_progress_mono) >= 1.0:
                    # Send kun en progress-event, SÆT IKKE STATUS
                    if self._event_bus:
                        task = asyncio.create_task(self._event_bus.publish(FileCopyProgressEvent(
                            file_id=tracked_file.id,
                            bytes_copied=bytes_copied,
                            total_bytes=current_file_size,
                            copy_speed_mbps=0 # Vi venter
                        )))
                        self._pending_tasks.add(task)
                        task.add_done_callback(self._pending_tasks.discard)
                    last_progress_mono = current_mono # Opdater tiden

            if file_finished_growing and bytes_copied >= current_file_size:
                # Post-exit safety re-read: check if file grew since we last read the size.
                # This prevents exiting with a stale current_file_size (incident 2026-03-27).
                final_size = await self._get_file_size(source_path)
                if final_size > bytes_copied:
                    logging.info(
                        f" FILE GREW AFTER GROWTH STOPPED: {os.path.basename(source_path)} "
                        f"(was {current_file_size}, now {final_size}) - continuing copy"
                    )
                    current_file_size = final_size
                    last_file_size = final_size
                    continue

                logging.info(
                    f" COPY COMPLETE: {os.path.basename(source_path)} ({bytes_copied} bytes)"
                )
                break

            if not file_finished_growing:
                await asyncio.sleep(poll_interval)

        return bytes_copied

    def is_file_currently_growing(self, tracked_file: TrackedFile) -> bool:
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
