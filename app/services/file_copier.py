"""
File Copier Service for File Transfer Agent.

FileCopyService er "arbejdshesten" 👷 der håndterer:
- Consumer pattern: Henter jobs fra JobQueueService
- Robust filkopiering med verifikation og fejlhåndtering
- Navnekonflikt resolution med _1, _2 suffixes
- Global vs. lokal fejlhåndtering med differentieret retry logic
- Progress tracking og StateManager integration

Implementeret efter roadmap Fase 4 specifikation.
"""

import asyncio
import aiofiles
import logging
from pathlib import Path
from typing import Optional, Dict

from app.config import Settings
from app.models import FileStatus, SpaceCheckResult
from app.services.state_manager import StateManager
from app.services.job_queue import JobQueueService


class FileCopyService:
    """
    File copier service der håndterer consumer pattern for filkopiering.
    
    Ansvar:
    1. Consumer Operations: Hent jobs fra JobQueueService
    2. Robust File Copying: Sikker filkopiering med verifikation
    3. Error Handling: Global vs. lokal fejlhåndtering
    4. Name Conflict Resolution: Automatisk _1, _2 suffixes
    5. Progress Tracking: Real-time opdateringer til StateManager
    """
    
    def __init__(self, settings: Settings, state_manager: StateManager, 
                 job_queue: JobQueueService, space_checker=None, space_retry_manager=None):
        """
        Initialize FileCopyService with dependencies.
        
        Args:
            settings: Application settings
            state_manager: Central state manager
            job_queue: Job queue service
            space_checker: Space checking utility (optional)
            space_retry_manager: Space retry manager (optional)
        """
        self.settings = settings
        self.state_manager = state_manager
        self.job_queue = job_queue
        self.space_checker = space_checker
        self.space_retry_manager = space_retry_manager
        self._logger = logging.getLogger("app.file_copier")
        
        # Copy statistics
        self._total_files_copied = 0
        self._total_bytes_copied = 0
        self._total_files_failed = 0
        
        # Service state
        self._running = False
        self._consumer_task: Optional[asyncio.Task] = None
        self._destination_available = True
        
        self._logger.info("FileCopyService initialiseret")
        self._logger.info(f"Source: {self.settings.source_directory}")
        self._logger.info(f"Destination: {self.settings.destination_directory}")
        self._logger.info(f"Use temporary files: {self.settings.use_temporary_file}")
    
    async def start_consumer(self) -> None:
        """
        Start consumer task der henter jobs fra queue og kopierer filer.
        
        Consumer kører indefinitely og håndterer både global og lokal fejlhåndtering.
        """
        if self._running:
            self._logger.warning("Consumer task er allerede startet")
            return
        
        self._running = True
        self._logger.info("File Copy Consumer startet")
        
        try:
            while self._running:
                # Check destination availability først
                if not await self._check_destination_availability():
                    await self._handle_global_error("Destination ikke tilgængelig")
                    continue
                
                # Hent næste job fra queue
                job = await self.job_queue.get_next_job()
                
                if job is None:
                    # Queue er tom - vent lidt og prøv igen
                    await asyncio.sleep(1)
                    continue
                
                # Process job
                await self._process_job(job)
                
        except asyncio.CancelledError:
            self._logger.info("File Copy Consumer blev cancelled")
            raise
        except Exception as e:
            self._logger.error(f"Kritisk fejl i consumer task: {e}")
            raise
        finally:
            self._running = False
            self._logger.info("File Copy Consumer stoppet")
    
    def stop_consumer(self) -> None:
        """Stop consumer task gracefully."""
        self._running = False
        self._logger.info("File Copy Consumer stop request")
    
    async def _check_destination_availability(self) -> bool:
        """
        Check om destination directory er tilgængelig.
        
        Returns:
            True hvis destination er tilgængelig
        """
        try:
            dest_path = Path(self.settings.destination_directory)
            
            # Check if destination exists og er writable
            if not dest_path.exists():
                self._logger.warning(f"Destination directory eksisterer ikke: {dest_path}")
                return False
            
            if not dest_path.is_dir():
                self._logger.warning(f"Destination er ikke en directory: {dest_path}")
                return False
            
            # Test write access med temporary fil
            test_file = dest_path / ".file_agent_test"
            try:
                async with aiofiles.open(test_file, 'w') as f:
                    await f.write("test")
                test_file.unlink()  # Slet test fil
                
                if not self._destination_available:
                    self._logger.info("Destination er igen tilgængelig")
                    self._destination_available = True
                
                return True
                
            except Exception as e:
                self._logger.warning(f"Kan ikke skrive til destination: {e}")
                return False
                
        except Exception as e:
            self._logger.error(f"Fejl ved check af destination availability: {e}")
            return False
    
    async def _handle_global_error(self, error_message: str) -> None:
        """
        Håndter global fejl med infinite retry og lang delay.
        
        Global fejl = destination utilgængelig, netværksproblemer osv.
        
        Args:
            error_message: Beskrivelse af global fejl
        """
        if self._destination_available:
            self._logger.warning(f"Global fejl detekteret: {error_message}")
            self._logger.warning(f"Pauser alle operationer i {self.settings.global_retry_delay_seconds} sekunder")
            self._destination_available = False
        
        # Infinite retry med lang delay
        await asyncio.sleep(self.settings.global_retry_delay_seconds)
    
    async def _process_job(self, job: Dict) -> None:
        """
        Process single job med space checking og lokal fejlhåndtering.
        
        Flow:
        1. Pre-flight space check (if enabled)
        2. Handle space shortage with retry logic
        3. Proceed with copy if space available
        4. Handle copy errors with retry logic
        
        Args:
            job: Job dictionary fra queue
        """
        file_path = job["file_path"]
        
        try:
            self._logger.info(f"Processing job: {file_path}")
            
            # Step 1: Pre-flight space check (if enabled and available)
            if self._should_check_space():
                space_check = await self._check_space_for_job(job)
                if not space_check.has_space:
                    await self._handle_space_shortage(job, space_check)
                    return  # Job will be retried later by SpaceRetryManager
            
            # Step 2: Opdater status til Copying
            await self.state_manager.update_file_status(
                file_path, 
                FileStatus.COPYING,
                copy_progress=0.0
            )
            
            # Step 3: Forsøg kopiering med retry logic
            success = await self._copy_file_with_retry(job)
            
            if success:
                # Mark job som completed
                await self.job_queue.mark_job_completed(job)
                self._total_files_copied += 1
                self._logger.info(f"Fil kopieret succesfuldt: {file_path}")
                
            else:
                # Permanent fejl - mark som failed
                await self.state_manager.update_file_status(
                    file_path,
                    FileStatus.FAILED,
                    error_message=f"Fejlede efter {self.settings.max_retry_attempts} forsøg"
                )
                await self.job_queue.mark_job_failed(job, "Max retry attempts reached")
                self._total_files_failed += 1
                self._logger.error(f"Fil kopiering fejlede permanent: {file_path}")
            
        except Exception as e:
            # Uventet fejl - treat som lokal fejl
            self._logger.error(f"Uventet fejl ved processing af job: {e}")
            await self.state_manager.update_file_status(
                file_path,
                FileStatus.FAILED,
                error_message=f"Uventet fejl: {str(e)}"
            )
            await self.job_queue.mark_job_failed(job, f"Unexpected error: {str(e)}")
            self._total_files_failed += 1
    
    async def _copy_file_with_retry(self, job: Dict) -> bool:
        """
        Kopier fil med retry logic for lokal fejlhåndtering.
        
        Lokal fejl = fil låst, permissions, korrupt fil osv.
        
        Args:
            job: Job dictionary
            
        Returns:
            True hvis kopiering lykkedes, False hvis permanent fejl
        """
        file_path = job["file_path"]
        max_attempts = self.settings.max_retry_attempts
        
        for attempt in range(1, max_attempts + 1):
            try:
                await self._copy_single_file(file_path, attempt, max_attempts)
                return True  # Success!
                
            except Exception as e:
                self._logger.warning(f"Kopiering fejlede (forsøg {attempt}/{max_attempts}): {file_path} - {e}")
                
                # Opdater retry count i StateManager
                await self.state_manager.update_file_status(
                    file_path,
                    FileStatus.COPYING,
                    retry_count=attempt,
                    error_message=f"Forsøg {attempt}: {str(e)}"
                )
                
                if attempt < max_attempts:
                    # Vent før næste forsøg
                    await asyncio.sleep(self.settings.retry_delay_seconds)
                else:
                    # Max attempts reached
                    self._logger.error(f"Max retry attempts nået for: {file_path}")
                    return False
        
        return False
    
    async def _copy_single_file(self, source_path: str, attempt: int, max_attempts: int) -> None:
        """
        Kopier single fil med verifikation og cleanup.
        
        Implementerer komplet copy workflow:
        1. Beregn destination path og håndter navnekonflikter
        2. Opret mapper hvis nødvendigt
        3. Kopier til temporary fil (hvis konfigureret)
        4. Verificer filstørrelse
        5. Omdøb temporary fil til final
        6. Slet original source fil
        7. Opdater status til Completed
        
        Args:
            source_path: Kilde fil path
            attempt: Nuværende forsøg nummer
            max_attempts: Total antal forsøg
            
        Raises:
            Exception: Ved enhver fejl under kopiering
        """
        source = Path(source_path)
        
        # 1. Check source file exists
        if not source.exists():
            raise FileNotFoundError(f"Source fil eksisterer ikke: {source_path}")
        
        if not source.is_file():
            raise ValueError(f"Source er ikke en fil: {source_path}")
        
        # 2. Beregn destination path med navnekonflikt resolution
        dest_final = await self._resolve_destination_path(source)
        
        # 3. Opret destination directory hvis nødvendigt
        dest_final.parent.mkdir(parents=True, exist_ok=True)
        
        # 4. Kopier fil (med eller uden temporary fil)
        if self.settings.use_temporary_file:
            dest_temp = dest_final.with_suffix(dest_final.suffix + ".tmp")
            await self._copy_with_progress(source, dest_temp, source_path)
            
            # 5. Verificer filstørrelse
            await self._verify_file_copy(source, dest_temp)
            
            # 6. Omdøb temporary til final
            dest_temp.rename(dest_final)
            self._logger.debug(f"Temporary fil omdøbt til final: {dest_final}")
            
        else:
            # Direct copy uden temporary fil
            await self._copy_with_progress(source, dest_final, source_path)
            
            # Verificer filstørrelse
            await self._verify_file_copy(source, dest_final)
        
        # 7. Slet original source fil
        source.unlink()
        self._logger.debug(f"Original source fil slettet: {source}")
        
        # 8. Opdater final statistics
        file_size = dest_final.stat().st_size
        self._total_bytes_copied += file_size
        
        # 9. Opdater status til Completed
        await self.state_manager.update_file_status(
            source_path,
            FileStatus.COMPLETED,
            copy_progress=100.0,
            error_message=None,
            retry_count=0
        )
        
        self._logger.info(f"Fil kopieret succesfuldt: {source} → {dest_final}")
    
    async def _resolve_destination_path(self, source: Path) -> Path:
        """
        Beregn destination path og håndter navnekonflikter.
        
        Implementerer navnekonflikt resolution:
        - video.mxf → video_1.mxf → video_2.mxf osv.
        
        Args:
            source: Source fil Path
            
        Returns:
            Destination Path uden konflikter
        """
        # Beregn relative path fra source directory
        source_base = Path(self.settings.source_directory)
        try:
            relative_path = source.relative_to(source_base)
        except ValueError:
            # Source er ikke under source directory - brug bare filename
            relative_path = source.name
        
        # Beregn initial destination path
        dest_base = Path(self.settings.destination_directory)
        dest_path = dest_base / relative_path
        
        # Check for navnekonflikt og løs det
        if not dest_path.exists():
            return dest_path
        
        # Navnekonflikt - generer _1, _2, osv. suffix
        return await self._resolve_name_conflict(dest_path)
    
    async def _resolve_name_conflict(self, dest_path: Path) -> Path:
        """
        Løs navnekonflikt ved at tilføje _1, _2 osv. suffix.
        
        Args:
            dest_path: Original destination path der har konflikt
            
        Returns:
            Ny destination path uden konflikt
        """
        stem = dest_path.stem  # Filnavn uden extension
        suffix = dest_path.suffix  # .mxf osv.
        parent = dest_path.parent
        
        counter = 1
        while True:
            new_name = f"{stem}_{counter}{suffix}"
            new_path = parent / new_name
            
            if not new_path.exists():
                self._logger.info(f"Navnekonflikt løst: {dest_path.name} → {new_name}")
                return new_path
            
            counter += 1
            
            # Safety check - undgå infinite loop
            if counter > 9999:
                raise RuntimeError(f"Kunne ikke løse navnekonflikt efter 9999 forsøg: {dest_path}")
    
    async def _copy_with_progress(self, source: Path, dest: Path, source_path: str) -> None:
        """
        Kopier fil med progress tracking og chunked reading.
        
        Args:
            source: Source Path
            dest: Destination Path  
            source_path: Original source path for StateManager updates
        """
        file_size = source.stat().st_size
        bytes_copied = 0
        chunk_size = 64 * 1024  # 64KB chunks
        last_progress_reported = -1  # Track last reported progress to avoid duplicate updates
        
        self._logger.debug(f"Starter chunk-wise copy: {source} → {dest} ({file_size} bytes)")
        
        try:
            async with aiofiles.open(source, 'rb') as src, aiofiles.open(dest, 'wb') as dst:
                while True:
                    chunk = await src.read(chunk_size)
                    if not chunk:
                        break
                    
                    await dst.write(chunk)
                    bytes_copied += len(chunk)
                    
                    # Calculate progress as whole number percentage
                    progress_percent = int((bytes_copied / file_size) * 100.0)
                    
                    # Only update when progress crosses a configured interval boundary
                    should_update = (
                        progress_percent != last_progress_reported and
                        progress_percent % self.settings.copy_progress_update_interval == 0
                    ) or bytes_copied == file_size  # Always update on completion
                    
                    if should_update:
                        await self.state_manager.update_file_status(
                            source_path,
                            FileStatus.COPYING,
                            copy_progress=float(progress_percent)
                        )
                        last_progress_reported = progress_percent
                        
                        self._logger.debug(f"Progress update: {progress_percent}% ({bytes_copied}/{file_size} bytes)")
            
            self._logger.debug(f"Copy completed: {bytes_copied} bytes copied")
            
        except Exception as e:
            # Cleanup partial destination fil ved fejl
            if dest.exists():
                try:
                    dest.unlink()
                    self._logger.debug(f"Cleaned up partial destination fil: {dest}")
                except Exception:
                    pass
            raise e
    
    async def _verify_file_copy(self, source: Path, dest: Path) -> None:
        """
        Verificer at fil blev kopieret korrekt ved sammenligning af filstørrelse.
        
        Args:
            source: Source Path
            dest: Destination Path
            
        Raises:
            ValueError: Hvis filstørrelser ikke matcher
        """
        source_size = source.stat().st_size
        dest_size = dest.stat().st_size
        
        if source_size != dest_size:
            raise ValueError(
                f"Filstørrelse mismatch: source={source_size}, dest={dest_size}"
            )
        
        self._logger.debug(f"Filstørrelse verificeret: {source_size} bytes")
    
    async def get_copy_statistics(self) -> Dict:
        """
        Hent detaljerede copy statistikker.
        
        Returns:
            Dictionary med copy statistikker
        """
        return {
            "is_running": self._running,
            "destination_available": self._destination_available,
            "total_files_copied": self._total_files_copied,
            "total_bytes_copied": self._total_bytes_copied,
            "total_files_failed": self._total_files_failed,
            "total_gb_copied": round(self._total_bytes_copied / (1024**3), 2),
            "settings": {
                "use_temporary_file": self.settings.use_temporary_file,
                "max_retry_attempts": self.settings.max_retry_attempts,
                "retry_delay_seconds": self.settings.retry_delay_seconds,
                "global_retry_delay_seconds": self.settings.global_retry_delay_seconds
            }
        }
    
    def get_consumer_status(self) -> Dict:
        """
        Hent consumer task status.
        
        Returns:
            Dictionary med consumer status
        """
        return {
            "is_running": self._running,
            "task_created": self._consumer_task is not None,
            "destination_available": self._destination_available
        }
    
    # Space management methods (SOLID - separated concerns)
    
    def _should_check_space(self) -> bool:
        """Check if space checking should be performed"""
        return (
            self.settings.enable_pre_copy_space_check and 
            self.space_checker is not None
        )
    
    async def _check_space_for_job(self, job: Dict) -> SpaceCheckResult:
        """
        Perform space check for a job.
        
        Args:
            job: Job dictionary containing file info
            
        Returns:
            SpaceCheckResult with space availability
        """
        # Get file size from job or tracked file
        file_size = job.get("file_size", 0)
        
        if file_size == 0:
            # Fallback: get from tracked file
            tracked_file = await self.state_manager.get_file(job["file_path"])
            if tracked_file:
                file_size = tracked_file.file_size
        
        return self.space_checker.check_space_for_file(file_size)
    
    async def _handle_space_shortage(self, job: Dict, space_check: SpaceCheckResult) -> None:
        """
        Handle insufficient disk space by scheduling retry.
        
        Args:
            job: Job that couldn't be processed due to space
            space_check: Result of space check
        """
        file_path = job["file_path"]
        
        self._logger.warning(
            f"Insufficient space for {file_path}: {space_check.reason}",
            extra={
                "operation": "space_shortage",
                "file_path": file_path,
                "available_gb": space_check.get_available_gb(),
                "required_gb": space_check.get_required_gb(),
                "shortage_gb": space_check.get_shortage_gb()
            }
        )
        
        # Use SpaceRetryManager if available, otherwise mark as failed
        if self.space_retry_manager:
            await self.space_retry_manager.schedule_space_retry(file_path, space_check)
        else:
            # Fallback: mark as failed if no retry manager
            await self.state_manager.update_file_status(
                file_path,
                FileStatus.FAILED,
                error_message=f"Insufficient space: {space_check.reason}"
            )
            await self.job_queue.mark_job_failed(job, "Insufficient disk space")
        
        # Mark job as handled (don't process further)
        await self.job_queue.mark_job_completed(job)