"""
Central State Manager for File Transfer Agent.

StateManager er "hjernen" i hele systemet - den centrale "single source of truth"
der holder styr på alle filer og deres status på en trådsikker måde.

Implementerer pub/sub pattern så andre services kan reagere på status ændringer.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Set, Callable, Awaitable
from datetime import datetime

from app.models import TrackedFile, FileStatus, FileStateUpdate


class StateManager:
    """
    Central state management for alle tracked filer.
    
    Denne klasse er designet som en singleton og håndterer:
    - Tilføjelse og fjernelse af filer
    - Status opdateringer med pub/sub events
    - Thread-safe operationer med asyncio.Lock
    - Cleanup af filer der ikke længere eksisterer
    """
    
    def __init__(self):
        """Initialize StateManager med tom tilstand."""
        self._files: Dict[str, TrackedFile] = {}
        self._lock = asyncio.Lock()
        self._subscribers: List[Callable[[FileStateUpdate], Awaitable[None]]] = []
        self._logger = logging.getLogger("app.state_manager")
        
        self._logger.info("StateManager initialiseret")
    
    async def add_file(self, file_path: str, file_size: int, last_write_time: Optional[datetime] = None) -> TrackedFile:
        """
        Tilføj en ny fil til tracking systemet.
        
        Args:
            file_path: Absolut sti til filen
            file_size: Filstørrelse i bytes  
            last_write_time: Sidste modificerings tidspunkt
            
        Returns:
            Det oprettede TrackedFile objekt
        """
        async with self._lock:
            if file_path in self._files:
                self._logger.debug(f"Fil allerede tracked: {file_path}")
                return self._files[file_path]
            
            tracked_file = TrackedFile(
                file_path=file_path,
                file_size=file_size,
                last_write_time=last_write_time,
                status=FileStatus.DISCOVERED
            )
            
            self._files[file_path] = tracked_file
            
            self._logger.info(f"Ny fil tilføjet: {file_path} ({file_size} bytes)")
            
            # Notify subscribers
            await self._notify(FileStateUpdate(
                file_path=file_path,
                old_status=None,
                new_status=FileStatus.DISCOVERED,
                tracked_file=tracked_file
            ))
            
            return tracked_file
    
    async def update_file_status(
        self, 
        file_path: str, 
        status: FileStatus, 
        **kwargs
    ) -> Optional[TrackedFile]:
        """
        Opdater status og andre attributter for en tracked fil.
        
        Args:
            file_path: Sti til filen der skal opdateres
            status: Ny status for filen
            **kwargs: Andre attributter der skal opdateres
            
        Returns:
            Det opdaterede TrackedFile objekt eller None hvis ikke fundet
        """
        async with self._lock:
            if file_path not in self._files:
                self._logger.warning(f"Forsøg på at opdatere ukendt fil: {file_path}")
                return None
            
            tracked_file = self._files[file_path]
            old_status = tracked_file.status
            
            # Opdater status
            tracked_file.status = status
            
            # Opdater andre attributter
            for key, value in kwargs.items():
                if hasattr(tracked_file, key):
                    setattr(tracked_file, key, value)
                else:
                    self._logger.warning(f"Ukendt attribut ignored: {key}")
            
            # Sæt tidsstempler baseret på status
            if status == FileStatus.COPYING and not tracked_file.started_copying_at:
                tracked_file.started_copying_at = datetime.now()
            elif status == FileStatus.COMPLETED and not tracked_file.completed_at:
                tracked_file.completed_at = datetime.now()
            
            self._logger.info(f"Status opdateret: {file_path} {old_status} -> {status}")
            
            # Notify subscribers
            await self._notify(FileStateUpdate(
                file_path=file_path,
                old_status=old_status,
                new_status=status,
                tracked_file=tracked_file
            ))
            
            return tracked_file
    
    async def remove_file(self, file_path: str) -> bool:
        """
        Fjern en fil fra tracking systemet.
        
        Args:
            file_path: Sti til filen der skal fjernes
            
        Returns:
            True hvis filen blev fjernet, False hvis den ikke eksisterede
        """
        async with self._lock:
            if file_path not in self._files:
                return False
            
            self._files.pop(file_path)
            
            self._logger.info(f"Fil fjernet fra tracking: {file_path}")
            
            # Note: Vi notificerer ikke subscribers for remove events
            # da det typisk sker ved cleanup og ikke er interessant for UI
            
            return True
    
    async def get_file(self, file_path: str) -> Optional[TrackedFile]:
        """
        Hent en specifik tracked fil.
        
        Args:
            file_path: Sti til filen
            
        Returns:
            TrackedFile objekt eller None hvis ikke fundet
        """
        async with self._lock:
            return self._files.get(file_path)
    
    async def get_all_files(self) -> List[TrackedFile]:
        """
        Hent alle tracked filer.
        
        Returns:
            Liste af alle TrackedFile objekter
        """
        async with self._lock:
            return list(self._files.values())
    
    async def get_files_by_status(self, status: FileStatus) -> List[TrackedFile]:
        """
        Hent alle filer med en specifik status.
        
        Args:
            status: Den ønskede status
            
        Returns:
            Liste af TrackedFile objekter med den givne status
        """
        async with self._lock:
            return [f for f in self._files.values() if f.status == status]
    
    async def get_file_count_by_status(self) -> Dict[FileStatus, int]:
        """
        Hent antal filer for hver status.
        
        Returns:
            Dictionary med status -> antal mapping
        """
        async with self._lock:
            counts = {}
            for status in FileStatus:
                counts[status] = len([f for f in self._files.values() if f.status == status])
            return counts
    
    async def cleanup_missing_files(self, existing_paths: Set[str]) -> int:
        """
        Fjern tracked filer som ikke længere eksisterer på filsystemet.
        
        Args:
            existing_paths: Set af stier til filer der stadig eksisterer
            
        Returns:
            Antal filer der blev fjernet
        """
        removed_count = 0
        
        async with self._lock:
            # Find filer der skal fjernes
            to_remove = []
            for file_path in self._files:
                if file_path not in existing_paths:
                    to_remove.append(file_path)
            
            # Fjern dem
            for file_path in to_remove:
                self._files.pop(file_path, None)
                removed_count += 1
                self._logger.debug(f"Cleanup: Fjernet {file_path}")
        
        if removed_count > 0:
            self._logger.info(f"Cleanup: Fjernede {removed_count} filer der ikke længere eksisterer")
        
        return removed_count
    
    def subscribe(self, callback: Callable[[FileStateUpdate], Awaitable[None]]) -> None:
        """
        Tilmeld til state change events.
        
        Args:
            callback: Async function der kaldes ved state changes
        """
        self._subscribers.append(callback)
        self._logger.debug(f"Ny subscriber tilmeldt. Total: {len(self._subscribers)}")
    
    def unsubscribe(self, callback: Callable[[FileStateUpdate], Awaitable[None]]) -> bool:
        """
        Afmeld fra state change events.
        
        Args:
            callback: Callback function der skal afmeldes
            
        Returns:
            True hvis callback blev fjernet, False hvis ikke fundet
        """
        try:
            self._subscribers.remove(callback)
            self._logger.debug(f"Subscriber afmeldt. Total: {len(self._subscribers)}")
            return True
        except ValueError:
            return False
    
    async def _notify(self, update: FileStateUpdate) -> None:
        """
        Notificer alle subscribers om en state change.
        
        Args:
            update: FileStateUpdate med event data
        """
        if not self._subscribers:
            return
        
        # Kald alle subscribers asynckront
        tasks = []
        for callback in self._subscribers:
            try:
                task = asyncio.create_task(callback(update))
                tasks.append(task)
            except Exception as e:
                self._logger.error(f"Fejl ved oprettelse af subscriber task: {e}")
        
        # Vent på alle callbacks, men log fejl hvis nogen fejler
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    self._logger.error(f"Subscriber {i} fejlede: {result}")
    
    async def get_statistics(self) -> Dict:
        """
        Hent statistik om systemets tilstand.
        
        Returns:
            Dictionary med forskellige statistikker
        """
        async with self._lock:
            total_files = len(self._files)
            status_counts = {}
            
            for status in FileStatus:
                status_counts[status.value] = len([f for f in self._files.values() if f.status == status])
            
            # Beregn total filstørrelse
            total_size = sum(f.file_size for f in self._files.values())
            
            # Find aktive kopiering
            copying_files = [f for f in self._files.values() if f.status == FileStatus.COPYING]
            
            return {
                "total_files": total_files,
                "status_counts": status_counts,
                "total_size_bytes": total_size,
                "active_copies": len(copying_files),
                "subscribers": len(self._subscribers)
            }