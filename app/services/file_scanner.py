"""
File Scanner Service for File Transfer Agent.

FileScannerService er "øjnene" 👀 i systemet der:
- Overvåger source directory kontinuerligt
- Opdager nye filer og tilføjer dem til StateManager
- Identificerer når filer er "stabile" (færdige med at blive skrevet)
- Promoverer stabile filer til READY status
- Cleaner up filer der er blevet slettet

Implementerer robust fil-stabilitet logik baseret på LastWriteTime tracking.
"""

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Set, Dict, Optional
import aiofiles.os

from app.config import Settings
from app.models import FileStatus
from app.services.state_manager import StateManager


class FileScannerService:
    """
    File scanner service der overvåger source directory for nye filer.
    
    Hovedansvar:
    1. Discovery: Find nye filer i source directory
    2. Stability Check: Vurder om filer er "stabile" (færdige)
    3. Status Management: Opdater fil status i StateManager
    4. Cleanup: Fjern tracking af slettede filer
    """
    
    def __init__(self, settings: Settings, state_manager: StateManager):
        """
        Initialize FileScannerService.
        
        Args:
            settings: Application settings med source path og timing
            state_manager: Central state manager til fil tracking
        """
        self.settings = settings
        self.state_manager = state_manager
        self._logger = logging.getLogger("app.file_scanner")
        
        # Internal tracking til fil-stabilitet
        self._file_last_seen: Dict[str, datetime] = {}
        self._file_last_write_times: Dict[str, datetime] = {}
        
        # Flag til at stoppe scanning loop
        self._running = False
        
        self._logger.info("FileScannerService initialiseret")
        self._logger.info(f"Overvåger: {settings.source_directory}")
        self._logger.info(f"Fil stabilitet: {settings.file_stable_time_seconds}s")
        self._logger.info(f"Polling interval: {settings.polling_interval_seconds}s")
    
    async def start_scanning(self) -> None:
        """
        Start den kontinuerlige fil scanning loop.
        
        Denne metode kører indefinitely indtil stop_scanning() kaldes.
        """
        if self._running:
            self._logger.warning("Scanner er allerede startet")
            return
        
        self._running = True
        self._logger.info("File Scanner startet")
        
        try:
            await self._scan_folder_loop()
        except asyncio.CancelledError:
            self._logger.info("File Scanner blev cancelled")
            raise
        except Exception as e:
            self._logger.error(f"Fejl i scanning loop: {e}")
            raise
        finally:
            self._running = False
            self._logger.info("File Scanner stoppet")
    
    def stop_scanning(self) -> None:
        """Stop fil scanning loop."""
        self._running = False
        self._logger.info("File Scanner stop request")
    
    async def _scan_folder_loop(self) -> None:
        """
        Hovedloop der kører kontinuerligt og scanner source directory.
        
        Workflow for hver iteration:
        1. Cleanup - fjern filer der ikke længere eksisterer
        2. Discovery - find nye filer og tilføj til StateManager
        3. Stability Check - vurder om Discovered filer er stabile
        4. Ready Promotion - opdater stabile filer til Ready status
        """
        while self._running:
            try:
                scan_start = datetime.now()
                
                # 1. Find alle filer i source directory
                current_files = await self._discover_files()
                
                # 2. Cleanup - fjern filer fra StateManager der ikke længere eksisterer
                await self._cleanup_missing_files(current_files)
                
                # 3. Cleanup - fjern gamle completed filer fra memory
                await self._cleanup_old_completed_files()
                
                # 4. Discovery - tilføj nye filer til StateManager
                await self._process_discovered_files(current_files)
                
                # 5. Stability Check - vurder stabilitet for Discovered filer
                await self._check_file_stability()
                
                scan_duration = (datetime.now() - scan_start).total_seconds()
                self._logger.debug(f"Scan iteration komplet på {scan_duration:.2f}s")
                
                # Vent før næste iteration
                await asyncio.sleep(self.settings.polling_interval_seconds)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error(f"Fejl i scan iteration: {e}")
                # Vent lidt før retry for at undgå tight error loop
                await asyncio.sleep(5)
    
    async def _discover_files(self) -> Set[str]:
        """
        Find alle MXF filer i source directory rekursivt.
        
        Returns:
            Set af absolutte file paths til alle fundne filer
        """
        discovered_files: Set[str] = set()
        
        try:
            source_path = Path(self.settings.source_directory)
            
            if not await aiofiles.os.path.exists(source_path):
                self._logger.warning(f"Source directory eksisterer ikke: {source_path}")
                return discovered_files
            
            if not await aiofiles.os.path.isdir(source_path):
                self._logger.error(f"Source path er ikke en directory: {source_path}")
                return discovered_files
            
            # Scan rekursivt for .mxf filer
            for root, dirs, files in os.walk(source_path):
                for file in files:
                    if file.lower().endswith('.mxf'):
                        file_path = os.path.join(root, file)
                        abs_file_path = os.path.abspath(file_path)
                        
                        # Filter out test files created by StorageMonitorService
                        if not self._should_ignore_file(abs_file_path):
                            discovered_files.add(abs_file_path)
            
            self._logger.debug(f"Opdagede {len(discovered_files)} MXF filer")
            
        except Exception as e:
            self._logger.error(f"Fejl ved discovery af filer: {e}")
        
        return discovered_files
    
    async def _cleanup_missing_files(self, current_files: Set[str]) -> None:
        """
        Fjern filer fra StateManager som ikke længere eksisterer på disk.
        
        Args:
            current_files: Set af file paths der eksisterer på disk
        """
        try:
            removed_count = await self.state_manager.cleanup_missing_files(current_files)
            
            if removed_count > 0:
                self._logger.info(f"Cleanup: Fjernede {removed_count} filer der ikke længere eksisterer")
            
            # Cleanup internal tracking data
            paths_to_remove = set(self._file_last_seen.keys()) - current_files
            for path in paths_to_remove:
                self._file_last_seen.pop(path, None)
                self._file_last_write_times.pop(path, None)
            
        except Exception as e:
            self._logger.error(f"Fejl ved cleanup af missing files: {e}")
    
    async def _cleanup_old_completed_files(self) -> None:
        """
        Fjern gamle completed filer fra memory for at holde memory usage nede.
        """
        try:
            removed_count = await self.state_manager.cleanup_old_completed_files(
                max_age_hours=self.settings.keep_completed_files_hours,
                max_count=self.settings.max_completed_files_in_memory
            )
            
            if removed_count > 0:
                self._logger.info(f"Cleanup: Fjernede {removed_count} gamle completed filer fra memory")
                
        except Exception as e:
            self._logger.error(f"Fejl ved cleanup af gamle completed filer: {e}")
    
    async def _process_discovered_files(self, current_files: Set[str]) -> None:
        """
        Process alle opdagede filer og tilføj nye til StateManager.
        
        Args:
            current_files: Set af file paths der eksisterer på disk
        """
        for file_path in current_files:
            try:
                # Tjek om filen allerede er tracked
                existing_file = await self.state_manager.get_file(file_path)
                if existing_file is not None:
                    continue  # Skip filer der allerede er tracked
                
                # Hent fil metadata
                file_stats = await self._get_file_stats(file_path)
                if file_stats is None:
                    continue  # Skip filer vi ikke kan læse
                
                file_size, last_write_time = file_stats
                
                # Skip tomme filer
                if file_size == 0:
                    self._logger.debug(f"Skipper tom fil: {file_path}")
                    continue
                
                # Tilføj fil til StateManager
                await self.state_manager.add_file(
                    file_path=file_path,
                    file_size=file_size,
                    last_write_time=last_write_time
                )
                
                # Initialize internal tracking
                self._file_last_seen[file_path] = datetime.now()
                self._file_last_write_times[file_path] = last_write_time
                
                self._logger.info(f"Ny fil opdaget: {os.path.basename(file_path)} ({file_size} bytes)")
                
            except Exception as e:
                self._logger.error(f"Fejl ved processing af fil {file_path}: {e}")
    
    async def _get_file_stats(self, file_path: str) -> Optional[tuple]:
        """
        Hent fil statistikker (størrelse og sidste write time).
        
        Args:
            file_path: Sti til filen
            
        Returns:
            Tuple (file_size, last_write_time) eller None ved fejl
        """
        try:
            stat_result = await aiofiles.os.stat(file_path)
            file_size = stat_result.st_size
            last_write_time = datetime.fromtimestamp(stat_result.st_mtime)
            return (file_size, last_write_time)
        
        except (OSError, IOError) as e:
            self._logger.warning(f"Kan ikke læse fil stats for {file_path}: {e}")
            return None
    
    async def _check_file_stability(self) -> None:
        """
        Tjek stabilitet for alle Discovered filer og promoter stabile til Ready.
        
        En fil er stabil hvis:
        1. LastWriteTime har været uændret i FILE_STABLE_TIME_SECONDS
        2. Filen kan læses (ikke låst)
        """
        try:
            # Hent alle Discovered filer
            discovered_files = await self.state_manager.get_files_by_status(FileStatus.DISCOVERED)
            
            for tracked_file in discovered_files:
                file_path = tracked_file.file_path
                
                # Tjek om filen stadig eksisterer
                if not await aiofiles.os.path.exists(file_path):
                    continue
                
                # Hent nuværende fil stats
                current_stats = await self._get_file_stats(file_path)
                if current_stats is None:
                    continue
                
                _, current_write_time = current_stats
                
                # Tjek om write time har ændret sig
                previous_write_time = self._file_last_write_times.get(file_path)
                if previous_write_time != current_write_time:
                    # Fil er stadig ved at blive skrevet til
                    self._file_last_write_times[file_path] = current_write_time
                    self._file_last_seen[file_path] = datetime.now()
                    
                    # Opdater file size mens filen vokser
                    current_file_size, _ = current_stats
                    if current_file_size != tracked_file.file_size:
                        await self.state_manager.update_file_status(
                            file_path=file_path,
                            status=FileStatus.DISCOVERED,  # Keep same status
                            file_size=current_file_size
                        )
                        self._logger.debug(
                            f"Fil størrelse opdateret: {os.path.basename(file_path)} "
                            f"({tracked_file.file_size} -> {current_file_size} bytes)"
                        )
                    
                    self._logger.debug(f"Fil stadig aktiv: {os.path.basename(file_path)}")
                    continue
                
                # Tjek om filen har været stabil længe nok
                last_seen = self._file_last_seen.get(file_path, datetime.now())
                stable_duration = (datetime.now() - last_seen).total_seconds()
                
                if stable_duration >= self.settings.file_stable_time_seconds:
                    # Fil er stabil - verificer at den kan læses
                    if await self._verify_file_accessible(file_path):
                        # Promoter til Ready status
                        await self.state_manager.update_file_status(
                            file_path=file_path,
                            status=FileStatus.READY
                        )
                        
                        # Cleanup internal tracking da filen nu er Ready
                        self._file_last_seen.pop(file_path, None)
                        self._file_last_write_times.pop(file_path, None)
                        
                        self._logger.info(f"Fil promoveret til Ready: {os.path.basename(file_path)}")
                    else:
                        self._logger.warning(f"Fil er stabil men ikke tilgængelig: {os.path.basename(file_path)}")
                
        except Exception as e:
            self._logger.error(f"Fejl ved stability check: {e}")
    
    async def _verify_file_accessible(self, file_path: str) -> bool:
        """
        Verificer at en fil kan tilgås (ikke låst).
        
        Args:
            file_path: Sti til filen
            
        Returns:
            True hvis filen kan tilgås, False ellers
        """
        try:
            # Forsøg at åbne filen i read mode for at verificere adgang
            async with aiofiles.open(file_path, 'rb') as f:
                # Læs bare de første par bytes for at verificere adgang
                await f.read(1024)
            return True
            
        except (OSError, IOError, PermissionError) as e:
            self._logger.debug(f"Fil ikke tilgængelig {file_path}: {e}")
            return False
    
    async def get_scanning_statistics(self) -> Dict:
        """
        Hent statistikker om scanning aktivitet.
        
        Returns:
            Dictionary med scanner statistikker
        """
        return {
            "is_running": self._running,
            "source_path": self.settings.source_directory,
            "files_being_tracked": len(self._file_last_seen),
            "polling_interval_seconds": self.settings.polling_interval_seconds,
            "file_stable_time_seconds": self.settings.file_stable_time_seconds
        }
    
    def _should_ignore_file(self, file_path: str) -> bool:
        """
        Check if file should be ignored by scanner.
        
        Filters out test files created by StorageMonitorService and macOS system files.
        
        Args:
            file_path: Absolute path to file to check
            
        Returns:
            True if file should be ignored
        """
        filename = os.path.basename(file_path)
        
        # Ignore storage test files
        if filename.startswith(self.settings.storage_test_file_prefix):
            self._logger.debug(f"Ignoring storage test file: {filename}")
            return True
        
        # Ignore macOS system files
        if filename == ".DS_Store":
            self._logger.debug(f"Ignoring macOS system file: {filename}")
            return True
            
        # Ignore other hidden system files
        if filename.startswith("._"):  # macOS AppleDouble files
            self._logger.debug(f"Ignoring macOS AppleDouble file: {filename}")
            return True
            
        # Add other ignore patterns here if needed
        # For example: temporary files, hidden files, etc.
        
        return False