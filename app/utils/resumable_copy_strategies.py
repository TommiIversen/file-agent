"""Resumable Copy Strategies"""

import asyncio
import time
from pathlib import Path
from typing import Optional, Callable
import logging

from ..services.copy_strategies import NormalFileCopyStrategy, GrowingFileCopyStrategy
from ..models import TrackedFile, FileStatus
from .secure_resume_config import (
    SecureResumeConfig,
    ResumeOperationMetrics,
    CONSERVATIVE_CONFIG,
)
from .secure_resume_verification import (
    SecureVerificationEngine,
    VerificationTimeout,
    QuickIntegrityChecker,
)

logger = logging.getLogger("app.utils.resumable_copy_strategies")


class ResumeCapableMixin:

    def __init__(self, *args, resume_config=None, file_copy_executor=None, **kwargs):
        # Extract resume_config before passing to super()
        self.resume_config: SecureResumeConfig = resume_config or CONSERVATIVE_CONFIG
        self.verification_engine = SecureVerificationEngine(self.resume_config)
        self._resume_metrics: Optional[ResumeOperationMetrics] = None

        # Pass remaining args to parent, ensuring file_copy_executor is included
        super().__init__(*args, file_copy_executor=file_copy_executor, **kwargs)

    async def should_attempt_resume(self, source_path: Path, dest_path: Path) -> bool:
        # Check om destination fil eksisterer
        if not dest_path.exists():
            logger.info(
                f"RESUME CHECK: Destination ikke fundet - starter fresh copy: {dest_path.name}"
            )
            return False

        # Quick integrity checks
        logger.info(
            f"RESUME CHECK: Destination exists - running quick integrity check: {dest_path.name}"
        )
        if not await QuickIntegrityChecker.quick_size_check(source_path, dest_path):
            logger.warning(
                f"RESUME CHECK: Quick size check failed - starter fresh copy: {dest_path.name}"
            )
            # Delete corrupt destination
            try:
                dest_path.unlink()
                logger.info(
                    f"RESUME CHECK: Deleted corrupt destination: {dest_path.name}"
                )
            except Exception as e:
                logger.error(
                    f"RESUME CHECK: Kunne ikke slette corrupt destination: {e}"
                )
            return False

        dest_size = dest_path.stat().st_size
        source_size = source_path.stat().st_size
        completion_pct = (dest_size / source_size) * 100 if source_size > 0 else 0

        logger.info(
            f"RESUME CHECK: Size comparison - {dest_size:,}/{source_size:,} bytes ({completion_pct:.1f}%)"
        )

        # Hvis dest er tom, start fresh
        if dest_size == 0:
            logger.info(
                f"RESUME CHECK: Destination er tom - starter fresh copy: {dest_path.name}"
            )
            return False

        # Hvis dest er komplet, skip helt
        if dest_size == source_size:
            # Quick tail check for at være sikker
            logger.info(
                f"RESUME CHECK: Komplet fil detecteret - running tail verification: {dest_path.name}"
            )
            if await QuickIntegrityChecker.quick_tail_check(source_path, dest_path):
                logger.info(
                    f"RESUME CHECK: Fil allerede komplet og verificeret - skipping: {dest_path.name}"
                )
                return False
            else:
                logger.warning(
                    f"RESUME CHECK: Komplet fil failed tail check - starter fresh copy: {dest_path.name}"
                )
                try:
                    dest_path.unlink()
                    logger.info(
                        f"RESUME CHECK: Deleted corrupt komplet fil: {dest_path.name}"
                    )
                except Exception as e:
                    logger.error(
                        f"RESUME CHECK: Kunne ikke slette corrupt komplet fil: {e}"
                    )
                return False

        # Hvis dest er for lille til at være værd at resume
        min_resume_size = max(
            self.resume_config.min_verify_bytes * 2,  # Mindst 2x verification size
            1024 * 1024,  # Eller 1MB minimum
        )

        if dest_size < min_resume_size:
            logger.info(
                f"RESUME CHECK: Destination for lille til resume ({dest_size:,} < {min_resume_size:,}) - "
                f"starter fresh copy: {dest_path.name}"
            )
            try:
                dest_path.unlink()
                logger.info(
                    f"RESUME CHECK: Deleted lille destination: {dest_path.name}"
                )
            except Exception as e:
                logger.error(f"RESUME CHECK: Kunne ikke slette lille destination: {e}")
            return False

        logger.info(
            f"Resume kandidat: {dest_path.name} "
            f"({dest_size:,}/{source_size:,} bytes = {(dest_size / source_size) * 100:.1f}%)"
        )
        return True

    async def execute_resume_copy(
        self,
        source_path: Path,
        dest_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> bool:
        operation_start = time.time()

        try:
            dest_size = dest_path.stat().st_size
            source_size = source_path.stat().st_size

            logger.info(f"RESUME COPY: Starting verification for {source_path.name}")
            logger.info(
                f"RESUME COPY: Current state - {dest_size:,}/{source_size:,} bytes ({(dest_size / source_size) * 100:.1f}%)"
            )

            # Find sikker resume position
            try:
                verification_start = time.time()
                logger.info(
                    f"RESUME COPY: Finding safe resume position using {self.resume_config.verification_mode} verification..."
                )

                (
                    resume_position,
                    metrics,
                ) = await self.verification_engine.find_safe_resume_position(
                    source_path, dest_path
                )
                self._resume_metrics = metrics

                verification_time = time.time() - verification_start
                bytes_preserved = resume_position
                preservation_pct = (
                    (bytes_preserved / source_size) * 100 if source_size > 0 else 0
                )

                logger.info(
                    f"RESUME COPY: Verification completed in {verification_time:.2f}s - "
                    f"can preserve {bytes_preserved:,} bytes ({preservation_pct:.1f}%)"
                )

                if self.resume_config.detailed_corruption_logging:
                    metrics.log_metrics()

            except VerificationTimeout as e:
                logger.error(
                    f"RESUME COPY: Verification timeout - fallback til fresh copy: {e}"
                )
                return await self._fallback_to_fresh_copy(
                    source_path, dest_path, progress_callback
                )

            except Exception as e:
                logger.error(
                    f"RESUME COPY: Verification error - fallback til fresh copy: {e}"
                )
                return await self._fallback_to_fresh_copy(
                    source_path, dest_path, progress_callback
                )

            # Hvis resume_position er 0, start fresh (men behold existing metrics)
            if resume_position == 0:
                logger.warning(
                    f"RESUME COPY: Resume position er 0 - ingen data kan preserveres, starter fresh copy: {source_path.name}"
                )
                return await self._fresh_copy_with_cleanup(
                    source_path, dest_path, progress_callback
                )

            # Truncate destination til resume position
            logger.info(
                f"RESUME COPY: Truncating destination til resume position {resume_position:,} bytes"
            )
            try:
                await self._truncate_destination(dest_path, resume_position)
                logger.info("RESUME COPY: Destination truncated successfully")
            except Exception as e:
                logger.error(
                    f"RESUME COPY: Kunne ikke truncate destination til {resume_position:,}: {e}"
                )
                return await self._fallback_to_fresh_copy(
                    source_path, dest_path, progress_callback
                )

            # Fortsæt copy fra resume position
            bytes_to_copy = source_size - resume_position
            logger.info(
                f"RESUME COPY: Continuing copy from position {resume_position:,}, {bytes_to_copy:,} bytes remaining"
            )

            success = await self._continue_copy_from_position(
                source_path, dest_path, resume_position, progress_callback
            )

            if success:
                elapsed = time.time() - operation_start
                source_size = source_path.stat().st_size
                bytes_resumed = source_size - resume_position

                logger.info(
                    f"Resume copy SUCCESS: {source_path.name} "
                    f"(resumed {bytes_resumed:,} bytes i {elapsed:.1f}s, "
                    f"bevarede {resume_position:,} bytes)"
                )
                return True
            else:
                logger.error(f"Resume copy FAILED: {source_path.name}")
                return False

        except Exception as e:
            logger.error(f"Uventet fejl under resume copy: {e}")
            return await self._fallback_to_fresh_copy(
                source_path, dest_path, progress_callback
            )

    async def _truncate_destination(self, dest_path: Path, position: int):
        if position < 0:
            raise ValueError(f"Invalid truncate position: {position}")

        current_size = dest_path.stat().st_size

        if position > current_size:
            raise ValueError(
                f"Cannot truncate to position {position:,} - fil er kun {current_size:,} bytes"
            )

        if position == current_size:
            logger.debug(
                "Truncate position matcher current size - ingen ændring nødvendig"
            )
            return

        logger.info(
            f"Truncating {dest_path.name} fra {current_size:,} til {position:,} bytes"
        )

        # Brug temporary fil for sikkerhed
        temp_path = dest_path.with_suffix(dest_path.suffix + ".truncate_temp")

        try:
            with dest_path.open("rb") as src, temp_path.open("wb") as dst:
                # Copy første 'position' bytes
                remaining = position
                buffer_size = 1024 * 1024  # 1MB buffer

                while remaining > 0:
                    chunk_size = min(buffer_size, remaining)
                    chunk = src.read(chunk_size)

                    if len(chunk) == 0:
                        break

                    dst.write(chunk)
                    remaining -= len(chunk)

            # Atomic replace
            temp_path.replace(dest_path)

            # Verify truncation
            new_size = dest_path.stat().st_size
            if new_size != position:
                raise RuntimeError(
                    f"Truncation verification failed: expected {position:,}, got {new_size:,}"
                )

            logger.debug(f"Truncation completed successfully: {position:,} bytes")

        except Exception as e:
            # Cleanup temp fil
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            raise RuntimeError(f"Truncation failed: {e}") from e

    async def _continue_copy_from_position(
        self,
        source_path: Path,
        dest_path: Path,
        start_position: int,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> bool:
        try:
            source_size = source_path.stat().st_size
            remaining_bytes = source_size - start_position

            if remaining_bytes <= 0:
                logger.debug("Ingen bytes tilbage at kopiere - copy komplet")
                return True

            logger.info(
                f"Fortsætter copy fra position {start_position:,} "
                f"({remaining_bytes:,} bytes tilbage)"
            )

            # Åbn filer for copy
            with source_path.open("rb") as src, dest_path.open("ab") as dst:
                src.seek(start_position)

                # Verify destination position
                dst_pos = dst.tell()
                if dst_pos != start_position:
                    raise RuntimeError(
                        f"Destination position mismatch: expected {start_position:,}, got {dst_pos:,}"
                    )

                # Copy data
                buffer_size = 2 * 1024 * 1024  # 2MB buffer for good performance
                copied_bytes = 0

                while copied_bytes < remaining_bytes:
                    chunk_size = min(buffer_size, remaining_bytes - copied_bytes)
                    chunk = src.read(chunk_size)

                    if len(chunk) == 0:
                        break

                    dst.write(chunk)
                    copied_bytes += len(chunk)

                    # Progress callback
                    if progress_callback:
                        total_copied = start_position + copied_bytes
                        progress_callback(total_copied, source_size)

                    # Yield control periodisk
                    if copied_bytes % (10 * 1024 * 1024) == 0:  # Every 10MB
                        await asyncio.sleep(0)

            # Verify final size
            final_size = dest_path.stat().st_size
            if final_size != source_size:
                raise RuntimeError(
                    f"Final size verification failed: expected {source_size:,}, got {final_size:,}"
                )

            logger.debug(f"Continued copy completed: {copied_bytes:,} bytes kopieret")
            return True

        except Exception as e:
            logger.error(f"Fejl under continued copy: {e}")
            return False

    async def _fallback_to_fresh_copy(
        self,
        source_path: Path,
        dest_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> bool:
        logger.info(f"Fallback til fresh copy: {source_path.name}")

        # Cleanup existing destination
        if dest_path.exists():
            try:
                dest_path.unlink()
            except Exception as e:
                logger.error(
                    f"Kunne ikke slette existing destination under fallback: {e}"
                )
                return False

        # Create a dummy TrackedFile for parent method
        dummy_tracked_file = TrackedFile(
            file_path=str(source_path),
            status=FileStatus.COPYING,
            size=source_path.stat().st_size,
            last_modified=source_path.stat().st_mtime,
        )

        # Brug parent class copy_file method
        return await super().copy_file(
            str(source_path), str(dest_path), dummy_tracked_file
        )

    async def _fresh_copy_with_cleanup(
        self,
        source_path: Path,
        dest_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> bool:
        logger.info(f"Fresh copy med cleanup: {source_path.name}")

        # Cleanup existing destination
        if dest_path.exists():
            try:
                dest_path.unlink()
                logger.debug("Slettet existing destination for fresh copy")
            except Exception as e:
                logger.error(f"Kunne ikke slette existing destination: {e}")
                # Continue anyway - måske kan vi overwrite

        # Create a dummy TrackedFile for parent method
        dummy_tracked_file = TrackedFile(
            file_path=str(source_path),
            status=FileStatus.COPYING,
            size=source_path.stat().st_size,
            last_modified=source_path.stat().st_mtime,
        )

        # Brug parent class copy_file method
        return await super().copy_file(
            str(source_path), str(dest_path), dummy_tracked_file
        )

    def get_resume_metrics(self) -> Optional[ResumeOperationMetrics]:
        return self._resume_metrics


class ResumableNormalFileCopyStrategy(ResumeCapableMixin, NormalFileCopyStrategy):

    async def copy_file(
        self, source_path: str, dest_path: str, tracked_file: TrackedFile
    ) -> bool:
        source = Path(source_path)
        dest = Path(dest_path)

        # Progress callback der opdaterer tracked_file
        def progress_callback(bytes_copied: int, total_bytes: int):
            if hasattr(tracked_file, "bytes_copied"):
                tracked_file.bytes_copied = bytes_copied
            if hasattr(tracked_file, "total_size"):
                tracked_file.total_size = total_bytes

        # Check om vi skal forsøge resume
        if await self.should_attempt_resume(source, dest):
            return await self.execute_resume_copy(source, dest, progress_callback)
        else:
            # Fresh copy - use parent implementation
            return await super().copy_file(source_path, dest_path, tracked_file)


class ResumableGrowingFileCopyStrategy(ResumeCapableMixin, GrowingFileCopyStrategy):

    async def copy_file(
        self, source_path: str, dest_path: str, tracked_file: TrackedFile
    ) -> bool:
        """
        Copy file med automatisk resume detection for growing files - FileCopyStrategy interface.

        Args:
            source_path: Source fil path som string
            dest_path: Destination fil path som string
            tracked_file: TrackedFile object for progress tracking

        Returns:
            True hvis copy succeeded, False ellers
        """
        source = Path(source_path)
        dest = Path(dest_path)

        # Progress callback der opdaterer tracked_file
        def progress_callback(bytes_copied: int, total_bytes: int):
            if hasattr(tracked_file, "bytes_copied"):
                tracked_file.bytes_copied = bytes_copied
            if hasattr(tracked_file, "total_size"):
                tracked_file.total_size = total_bytes

        # Growing files har special considerations for resume
        if await self.should_attempt_resume(source, dest):
            # For growing files, vi er mere konservative med resume
            # fordi filen kan stadig være under ændring

            dest_size = dest.stat().st_size
            source_size = source.stat().st_size

            # Hvis destination er meget tæt på source size,
            # kan det være growing file der er færdig
            size_diff = source_size - dest_size

            if size_diff < 1024 * 1024:  # Mindre end 1MB forskel
                logger.info(
                    f"Growing file tæt på completion - forsøger resume: "
                    f"{source.name} (mangler {size_diff:,} bytes)"
                )
                return await self.execute_resume_copy(source, dest, progress_callback)
            else:
                logger.info(
                    f"Growing file betydelig size difference - fresh copy: "
                    f"{source.name} (mangler {size_diff:,} bytes)"
                )
                return await self._fresh_copy_with_cleanup(
                    source, dest, progress_callback
                )
        else:
            # Fresh copy - use parent implementation
            return await super().copy_file(source_path, dest_path, tracked_file)


class ResumeStrategyFactory:

    @staticmethod
    def create_normal_strategy(
        resume_config: Optional[SecureResumeConfig] = None,
    ) -> ResumableNormalFileCopyStrategy:
        """
        Create resumable normal file copy strategy.
        """
        config = resume_config or CONSERVATIVE_CONFIG
        return ResumableNormalFileCopyStrategy(resume_config=config)

    @staticmethod
    def create_growing_strategy(
        resume_config: Optional[SecureResumeConfig] = None, **growing_params
    ) -> ResumableGrowingFileCopyStrategy:
        """
        Create resumable growing file copy strategy.
        """
        config = resume_config or CONSERVATIVE_CONFIG
        return ResumableGrowingFileCopyStrategy(resume_config=config, **growing_params)

    @staticmethod
    def create_strategy_for_file(
        file_path: Path,
        is_growing: bool = False,
        resume_config: Optional[SecureResumeConfig] = None,
        **growing_params,
    ):
        """
        Create appropriate strategy baseret på fil karakteristika.
        """
        if is_growing:
            return ResumeStrategyFactory.create_growing_strategy(
                resume_config, **growing_params
            )
        else:
            return ResumeStrategyFactory.create_normal_strategy(resume_config)
