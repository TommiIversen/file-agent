"""
Datamodeller for File Transfer Agent.

Indeholder alle Pydantic modeller og enums der definerer 
systemets grundlæggende datastrukturer.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class FileStatus(str, Enum):
    """
    Status for en tracked fil gennem hele kopieringsprocessen.
    
    Workflow: Discovered -> Ready -> InQueue -> Copying -> Completed
    Alternative: -> Failed (ved fejl)
    """
    DISCOVERED = "Discovered"    # Fil fundet, men ikke stabil endnu
    READY = "Ready"             # Fil er stabil og klar til kopiering
    IN_QUEUE = "InQueue"        # Fil er tilføjet til job queue
    COPYING = "Copying"         # Fil er ved at blive kopieret
    COMPLETED = "Completed"     # Fil er succesfuldt kopieret og slettet
    FAILED = "Failed"           # Fil kunne ikke kopieres (permanent fejl)


class TrackedFile(BaseModel):
    """
    Central datastruktur der repræsenterer en fil gennem hele kopieringsprocessen.
    
    Bruges af StateManager til at holde styr på alle filer og deres tilstand.
    Indeholder både metadata og progress information.
    """
    
    file_path: str = Field(
        ..., 
        description="Absolut sti til kildefilen"
    )
    
    status: FileStatus = Field(
        default=FileStatus.DISCOVERED,
        description="Filens nuværende status i workflow'et"
    )
    
    file_size: int = Field(
        default=0,
        ge=0,
        description="Filstørrelse i bytes"
    )
    
    last_write_time: Optional[datetime] = Field(
        default=None,
        description="Sidste gang filen blev modificeret (til stabilitetschek)"
    )
    
    copy_progress: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Kopieringsprogress i procent (0-100)"
    )
    
    error_message: Optional[str] = Field(
        default=None,
        description="Fejlbesked hvis status er FAILED"
    )
    
    retry_count: int = Field(
        default=0,
        ge=0,
        description="Antal retry forsøg for denne fil"
    )
    
    discovered_at: datetime = Field(
        default_factory=datetime.now,
        description="Tidspunkt hvor filen blev opdaget"
    )
    
    started_copying_at: Optional[datetime] = Field(
        default=None,
        description="Tidspunkt hvor kopiering startede"
    )
    
    completed_at: Optional[datetime] = Field(
        default=None,
        description="Tidspunkt hvor kopiering blev færdig"
    )
    
    destination_path: Optional[str] = Field(
        default=None,
        description="Sti til destination filen (med evt. navnekonflikt suffix)"
    )

    model_config = ConfigDict(
        # Eksempel data til dokumentation
        json_schema_extra={
            "example": {
                "file_path": "/source/video_clip_001.mxv",
                "status": "Copying",
                "file_size": 1073741824,
                "last_write_time": "2025-10-08T14:30:00",
                "copy_progress": 67.5,
                "error_message": None,
                "retry_count": 0,
                "discovered_at": "2025-10-08T14:25:00",
                "started_copying_at": "2025-10-08T14:27:00",
                "completed_at": None,
                "destination_path": "/destination/video_clip_001.mxv"
            }
        }
    )


class FileStateUpdate(BaseModel):
    """
    Event data structure for pub/sub system.
    
    Bruges til at notificere subscribers om ændringer i fil status.
    """
    
    file_path: str
    old_status: Optional[FileStatus]
    new_status: FileStatus
    tracked_file: TrackedFile
    timestamp: datetime = Field(default_factory=datetime.now)

    model_config = ConfigDict()