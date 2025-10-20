"""Secure Resume Verification Engine"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Tuple

from .secure_resume_config import SecureResumeConfig, ResumeOperationMetrics

logger = logging.getLogger("app.utils.secure_resume_verification")


class VerificationTimeout(Exception):
    pass


class SecureVerificationEngine:

    def __init__(self, config: SecureResumeConfig):
        self.config = config
        self._verification_start_time: Optional[float] = None

    async def find_safe_resume_position(
            self, source_path: Path, dest_path: Path
    ) -> Tuple[int, ResumeOperationMetrics]:
        start_time = time.time()
        self._verification_start_time = start_time

        try:
            # Validate files exist
            if not source_path.exists():
                raise FileNotFoundError(f"Source fil ikke fundet: {source_path}")
            if not dest_path.exists():
                raise FileNotFoundError(f"Destination fil ikke fundet: {dest_path}")

            # Get file sizes
            source_size = source_path.stat().st_size
            dest_size = dest_path.stat().st_size

            if self.config.detailed_corruption_logging:
                logger.info(
                    f"Starter verification: source={source_size:,}B, dest={dest_size:,}B"
                )

            # Safety check: dest kan ikke være større end source
            if dest_size > source_size:
                logger.warning(
                    f"Destination fil ({dest_size:,}B) er større end source ({source_size:,}B) - "
                    f"potentiel corruption detekteret"
                )
                corruption_metrics = ResumeOperationMetrics(
                    file_size_bytes=source_size,
                    dest_size_bytes=dest_size,
                    verification_bytes=0,
                    verification_time_seconds=time.time() - start_time,
                    corruption_detected=True,
                    corruption_offset=source_size,
                    bytes_preserved=source_size,
                    resume_position=source_size,
                    binary_search_iterations=0,
                )
                return source_size, corruption_metrics

            # Beregn verification størrelse
            verification_size = self.config.get_verification_size_for_file(dest_size)
            verification_start = max(0, dest_size - verification_size)

            if self.config.log_verification_progress:
                logger.info(
                    f"Verificerer region: offset={verification_start:,}, "
                    f"size={verification_size:,} ({verification_size / 1024 / 1024:.1f}MB)"
                )

            # Først: verificer den region vi har planlagt
            initial_verification_ok = await self._verify_region_with_timeout(
                source_path, dest_path, verification_start, verification_size
            )

            if initial_verification_ok:
                # Alt ser godt ud - resume fra slutningen
                success_metrics = ResumeOperationMetrics(
                    file_size_bytes=source_size,
                    dest_size_bytes=dest_size,
                    verification_bytes=verification_size,
                    verification_time_seconds=time.time() - start_time,
                    corruption_detected=False,
                    bytes_preserved=dest_size,
                    resume_position=dest_size,
                    binary_search_iterations=0,
                )

                if self.config.detailed_corruption_logging:
                    logger.info(
                        f"Verification SUCCESS: resuming fra {dest_size:,} bytes"
                    )

                return dest_size, success_metrics

            # Corruption detekteret - find præcist hvor
            logger.warning(
                "Corruption detekteret i verification region - starter binary search"
            )

            (
                safe_position,
                binary_iterations,
            ) = await self._binary_search_corruption_point(
                source_path, dest_path, verification_start, dest_size
            )

            # Anvend safety margin
            safety_margin = self.config.get_safety_margin_bytes()
            final_position = max(0, safe_position - safety_margin)
            bytes_preserved = final_position

            corruption_metrics = ResumeOperationMetrics(
                file_size_bytes=source_size,
                dest_size_bytes=dest_size,
                verification_bytes=dest_size - verification_start,  # Total verificeret
                verification_time_seconds=time.time() - start_time,
                corruption_detected=True,
                corruption_offset=safe_position,
                bytes_preserved=bytes_preserved,
                resume_position=final_position,
                binary_search_iterations=binary_iterations,
            )

            if self.config.detailed_corruption_logging:
                logger.warning(
                    f"Corruption point fundet ved {safe_position:,} bytes. "
                    f"Resume position: {final_position:,} bytes "
                    f"(bevarer {bytes_preserved:,}/{dest_size:,} bytes = "
                    f"{(bytes_preserved / dest_size) * 100:.1f}%)"
                )

            return final_position, corruption_metrics

        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            logger.error(f"Verification timeout efter {elapsed:.1f}s - starter forfra")
            raise VerificationTimeout(f"Verification timeout efter {elapsed:.1f}s")

    async def _verify_region_with_timeout(
            self, source_path: Path, dest_path: Path, offset: int, size: int
    ) -> bool:
        timeout = self.config.max_verification_time_seconds

        try:
            return await asyncio.wait_for(
                self._verify_region_exact(source_path, dest_path, offset, size),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.error(f"Region verification timeout efter {timeout}s")
            raise

    async def _verify_region_exact(
            self, source_path: Path, dest_path: Path, offset: int, size: int
    ) -> bool:
        if size <= 0:
            return True

        buffer_size = self.config.get_verification_buffer_size()

        # Check timeout periodisk
        last_timeout_check = time.time()
        timeout_check_interval = 1.0  # Check every second

        try:
            async with self._open_files_for_verification(source_path, dest_path) as (
                    src_file,
                    dst_file,
            ):
                # Seek til start position
                src_file.seek(offset)
                dst_file.seek(offset)

                remaining = size
                bytes_verified = 0

                while remaining > 0:
                    # Periodic timeout check
                    current_time = time.time()
                    if current_time - last_timeout_check > timeout_check_interval:
                        self._check_verification_timeout()
                        last_timeout_check = current_time

                    # Læs næste chunk
                    chunk_size = min(buffer_size, remaining)

                    src_chunk = src_file.read(chunk_size)
                    dst_chunk = dst_file.read(chunk_size)

                    # Verificer chunk størrelse først
                    if len(src_chunk) != len(dst_chunk):
                        if self.config.detailed_corruption_logging:
                            logger.warning(
                                f"Chunk størrelse mismatch ved offset {offset + bytes_verified}: "
                                f"src={len(src_chunk)}, dst={len(dst_chunk)}"
                            )
                        return False

                    # Verificer chunk indhold
                    if src_chunk != dst_chunk:
                        if self.config.detailed_corruption_logging:
                            # Find første mismatch byte
                            for i, (sb, db) in enumerate(zip(src_chunk, dst_chunk)):
                                if sb != db:
                                    mismatch_offset = offset + bytes_verified + i
                                    logger.warning(
                                        f"Byte mismatch ved offset {mismatch_offset}: "
                                        f"src=0x{sb:02x}, dst=0x{db:02x}"
                                    )
                                    break
                        return False

                    remaining -= chunk_size
                    bytes_verified += chunk_size

                    # Progress logging (kun hvis enabled)
                    if (
                            self.config.log_verification_progress
                            and bytes_verified % (10 * 1024 * 1024) == 0
                    ):
                        logger.debug(f"Verificeret {bytes_verified:,}/{size:,} bytes")

                    # Yield control periodisk for bedre async performance
                    if bytes_verified % (1024 * 1024) == 0:  # Every MB
                        await asyncio.sleep(0)  # Yield to event loop

                return True

        except Exception as e:
            logger.error(f"Fejl under region verification: {e}")
            return False

    @asynccontextmanager
    async def _open_files_for_verification(self, source_path: Path, dest_path: Path):
        src_file = None
        dst_file = None
        try:
            # Åbn filer i binary mode
            src_file = source_path.open("rb")
            dst_file = dest_path.open("rb")
            yield src_file, dst_file
        finally:
            # Ensure filer bliver lukket
            if src_file:
                src_file.close()
            if dst_file:
                dst_file.close()

    async def _binary_search_corruption_point(
            self, source_path: Path, dest_path: Path, start_offset: int, end_offset: int
    ) -> Tuple[int, int]:
        chunk_size = self.config.get_binary_search_chunk_size()
        iterations = 0
        max_iterations = self.config.max_corruption_search_attempts

        left = start_offset
        right = end_offset
        last_good_position = start_offset

        if self.config.detailed_corruption_logging:
            logger.info(
                f"Binary search for corruption: range=[{left:,}, {right:,}], "
                f"chunk_size={chunk_size:,}"
            )

        while right - left > chunk_size and iterations < max_iterations:
            iterations += 1

            # Check timeout
            self._check_verification_timeout()

            mid = (
                    left + ((right - left) // chunk_size) * chunk_size
            )  # Align til chunk boundary
            verify_size = min(chunk_size, right - mid)

            if self.config.log_verification_progress:
                logger.debug(
                    f"Binary search iteration {iterations}: checking [{mid:,}, {mid + verify_size:,}]"
                )

            try:
                region_ok = await self._verify_region_with_timeout(
                    source_path, dest_path, mid, verify_size
                )

                if region_ok:
                    # Denne region er OK - corruption er til højre
                    last_good_position = mid + verify_size
                    left = mid + verify_size
                    if self.config.log_verification_progress:
                        logger.debug(
                            f"Region OK - corruption efter {last_good_position:,}"
                        )
                else:
                    # Corruption i denne region - søg til venstre
                    right = mid
                    if self.config.log_verification_progress:
                        logger.debug(f"Corruption i region - søger før {mid:,}")

            except asyncio.TimeoutError:
                logger.warning(f"Timeout under binary search iteration {iterations}")
                break

            # Yield control
            await asyncio.sleep(0)

        if iterations >= max_iterations:
            logger.warning(
                f"Binary search nåede max iterationer ({max_iterations}) - "
                f"bruger position {last_good_position:,}"
            )

        if self.config.detailed_corruption_logging:
            logger.info(
                f"Binary search afsluttet efter {iterations} iterationer. "
                f"Sidste gode position: {last_good_position:,}"
            )

        return last_good_position, iterations

    def _check_verification_timeout(self):
        if self._verification_start_time is None:
            return

        elapsed = time.time() - self._verification_start_time
        if elapsed > self.config.max_verification_time_seconds:
            raise VerificationTimeout(
                f"Verification timeout: {elapsed:.1f}s > {self.config.max_verification_time_seconds}s"
            )


class QuickIntegrityChecker:

    @staticmethod
    async def quick_size_check(source_path: Path, dest_path: Path) -> bool:
        """
        Hurtig størrelse check - dest må ikke være større end source.
        """
        if not source_path.exists() or not dest_path.exists():
            return False

        source_size = source_path.stat().st_size
        dest_size = dest_path.stat().st_size

        return dest_size <= source_size

    @staticmethod
    async def quick_tail_check(
            source_path: Path, dest_path: Path, check_bytes: int = 1024
    ) -> bool:
        """
        Hurtig check af de sidste N bytes.
        """
        try:
            if not source_path.exists() or not dest_path.exists():
                return False

            dest_size = dest_path.stat().st_size
            if dest_size < check_bytes:
                check_bytes = dest_size

            if check_bytes <= 0:
                return True

            with source_path.open("rb") as src, dest_path.open("rb") as dst:
                # Seek til slutningen minus check_bytes
                src.seek(-check_bytes, 2)  # From end
                dst.seek(-check_bytes, 2)  # From end

                src_tail = src.read(check_bytes)
                dst_tail = dst.read(check_bytes)

                return src_tail == dst_tail

        except Exception as e:
            logger.warning(f"Quick tail check failed: {e}")
            return False
